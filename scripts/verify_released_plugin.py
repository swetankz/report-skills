#!/usr/bin/env python3
"""Verify Report Skills in an ephemeral GitHub-hosted Windows environment.

The workflow calling this script supplies a disposable runner. It downloads the
official Codex CLI 0.166.0 Windows ARM64 executable, creates a local plugin
marketplace from the exact verified plugin ZIP, performs the documented local
installation sequence, and checks model-free skills discovery.

This script grants no release-publication authority and does not make model
calls, start a thread or turn, modify Git credentials, or change another user's
Codex installation. It is intentionally Windows-specific because it verifies
the Windows known-folder discovery path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from create_release_package import plugin_inventory  # noqa: E402
from release_inventory import hash_inventory  # noqa: E402
from verify_release_artifacts import verify_archive  # noqa: E402

SEMVER_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")

CODEX_URL = (
    "https://github.com/openai/codex/releases/download/rust-v0.166.0/"
    "codex-aarch64-pc-windows-msvc.exe"
)
CODEX_SHA256 = "d92bb6a3259980a742049882f396eb09eb26734589accc7f2c5173b7ab926138"


class VerificationError(RuntimeError):
    pass


def require(condition: object, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def plugin_manifest_from_archive(archive: Path) -> dict[str, object]:
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read(".codex-plugin/plugin.json").decode("utf-8"))
    require(isinstance(manifest, dict), "Plugin manifest is not an object")
    return manifest


def verify_candidate_sidecar(archive: Path) -> str:
    sidecar = archive.with_name(archive.name + ".sha256")
    fields = sidecar.read_text(encoding="utf-8").strip().split()
    require(len(fields) == 2 and fields[1] == archive.name, f"Invalid checksum sidecar: {sidecar.name}")
    expected, filename = fields
    require(filename == archive.name, f"Checksum sidecar names the wrong archive: {filename}")
    require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"Invalid checksum sidecar digest format: {expected}")
    actual = sha256_file(archive)
    require(actual == expected.lower(), f"Checksum mismatch for {archive.name}")
    return actual


def tree_hash_inventory(root: Path, archive: Path) -> dict[str, str]:
    root = root.resolve()
    expected: dict[str, str] = {}
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            expected[info.filename] = sha256_bytes(source.read(info))
    actual: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if path.is_symlink():
            raise VerificationError(f"Refusing linked payload entry: {path}")
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = sha256_file(path)
        elif path.is_dir():
            continue
        else:
            raise VerificationError(f"Unexpected payload entry type: {path}")
    require(set(actual) == set(expected), "Payload entry set differs from verified candidate ZIP")
    mismatches = {path for path in expected if actual[path] != expected[path]}
    require(not mismatches, f"Payload hashes differ from verified candidate ZIP: {sorted(mismatches)}")
    return actual


def normalize_for_compare(value: object) -> str:
    text = str(value)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.abspath(text))


def download_codex(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    digest = hashlib.sha256()
    with urllib.request.urlopen(CODEX_URL, timeout=120) as response:
        with destination.open("xb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
    observed = digest.hexdigest()
    require(
        observed == CODEX_SHA256,
        f"Official Codex asset digest mismatch: {observed}",
    )


def extract_verified_plugin(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        names = source.infolist()
        require(not any(info.is_dir() for info in names), "Directory entries are forbidden in plugin archives")
        for info in names:
            raw_parts = PurePosixPath(info.filename).parts
            require(
                bool(info.filename)
                and not info.filename.startswith("/")
                and all(part not in {"", ".", ".."} for part in raw_parts),
                f"Unsafe archive member path: {info.filename!r}",
            )
        source.extractall(destination)


def copy_payload(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for path in sorted(source.iterdir(), key=lambda item: item.name.casefold()):
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target, symlinks=False)
        else:
            shutil.copy2(path, target)


def create_wrapper(extracted: Path, wrapper: Path) -> dict[str, object]:
    require(not wrapper.exists(), "Marketplace wrapper destination already exists")
    payload = wrapper / "plugins" / "report-skills"
    payload.parent.mkdir(parents=True)
    copy_payload(extracted, payload)

    catalog = {
        "name": "report-skills-local",
        "interface": {"displayName": "Report Skills local"},
        "plugins": [
            {
                "name": "report-skills",
                "source": {"source": "local", "path": "./plugins/report-skills"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }
    catalog_path = wrapper / ".agents" / "plugins" / "marketplace.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_bytes(json_bytes(catalog))
    require((payload / ".codex-plugin" / "plugin.json").is_file(), "Wrapped plugin manifest is missing")
    require(not catalog_path.read_bytes().startswith(b"\xef\xbb\xbf"), "Wrapper catalog has a UTF-8 BOM")
    return {
        "root": str(wrapper.resolve()),
        "catalog": str(catalog_path.resolve()),
        "catalog_sha256": sha256_file(catalog_path),
        "payload_root": str(payload.resolve()),
    }


def make_environment(workspace: Path, codex_home: Path, temp: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    allowed = {
        "systemroot",
        "windir",
        "comspec",
        "pathext",
        "path",
        "systemdrive",
        "os",
        "programfiles",
        "programfiles(x86)",
        "programw6432",
        "commonprogramfiles",
        "commonprogramfiles(x86)",
        "commonprogramw6432",
        "number_of_processors",
        "processor_architecture",
        "processor_identifier",
        "processor_level",
        "processor_revision",
        "username",
        "computername",
    }
    for key, value in os.environ.items():
        if key.lower() in allowed:
            env[key] = value
    user_profile = os.environ["USERPROFILE"]
    drive, tail = os.path.splitdrive(user_profile)
    env.update(
        {
            "USERPROFILE": user_profile,
            "HOME": user_profile,
            "HOMEDRIVE": drive,
            "HOMEPATH": tail,
            "CODEX_HOME": str(codex_home),
            "TMP": str(temp),
            "TEMP": str(temp),
            "TMPDIR": str(temp),
            "NO_COLOR": "1",
            "TERM": "dumb",
            "POWERSHELL_TELEMETRY_OPTOUT": "1",
        }
    )
    return env


def run_command(
    argv: list[Path | str],
    *,
    cwd: Path,
    env: dict[str, str],
    allowed_exit_codes: tuple[int, ...] = (0,),
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        [str(part) for part in argv],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    require(
        result.returncode in allowed_exit_codes,
        f"{' '.join(str(part) for part in argv)} failed with exit code {result.returncode}: "
        + result.stderr.decode("utf-8", errors="replace"),
    )
    return result


def json_documents(payload: bytes) -> list[object]:
    text = payload.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    decoded: list[object] = []
    offset = 0
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset == len(text):
            break
        item, offset = decoder.raw_decode(text, offset)
        decoded.append(item)
    return decoded


def skills_list(codex: Path, *, cwd: Path, env: dict[str, str], client_version: str, timeout: int = 45) -> dict[str, object]:
    process = subprocess.Popen(
        [str(codex), "app-server", "--stdio"],
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    events: queue.Queue[bytes | None] = queue.Queue()
    messages: list[dict[str, object]] = []
    stderr_data = bytearray()

    def read_stdout() -> None:
        try:
            while True:
                line = process.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    break
                events.put(line)
        finally:
            events.put(None)

    def read_stderr() -> None:
        while chunk := process.stderr.read(4096):
            stderr_data.extend(chunk)

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    def send(message: dict[str, object]) -> None:
        require(
            message.get("method") in {"initialize", "initialized", "skills/list"},
            f"Refusing non-model-free protocol method: {message.get('method')}",
        )
        process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
        process.stdin.flush()

    def receive(request_id: int) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, f"Timed out waiting for response {request_id}")
            try:
                line = events.get(timeout=remaining)
            except queue.Empty:
                raise VerificationError(f"Timed out waiting for response {request_id}")
            if line is None:
                raise VerificationError("Codex app-server exited before the expected response")
            message = json.loads(line.decode("utf-8", errors="strict"))
            require(isinstance(message, dict), "App-server emitted a non-object message")
            messages.append(message)
            if "error" in message:
                raise VerificationError(f"Codex app-server returned error: {message['error']}")
            if message.get("id") == request_id:
                require("result" in message, "Metadata response is missing result")
                result = message["result"]
                require(isinstance(result, dict), "Metadata response result is not an object")
                return result
            require(
                not ("id" in message and "method" in message),
                "Codex requested approval or other user input; stopping",
            )

    forced_shutdown = False
    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "report_skills_release_candidate_verification",
                        "title": "Report Skills release candidate verification",
                        "version": client_version,
                    },
                    "capabilities": {
                        "experimentalApi": False,
                        "explicitGatewayOauth": False,
                        "requestAttestation": False,
                        "mcpServerOpenaiFormElicitation": False,
                    },
                },
            }
        )
        receive(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "skills/list", "params": {"cwds": [str(cwd)], "forceReload": True}})
        result = receive(2)
    except BaseException:
        forced_shutdown = True
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        raise
    finally:
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                forced_shutdown = True
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

    require(not forced_shutdown, "Codex app-server required forced shutdown")
    require(process.returncode == 0, f"Codex app-server exited with code {process.returncode}")
    result["_stderr_excerpt"] = stderr_data[:4096].decode("utf-8", errors="replace")
    result["_messages_seen"] = messages
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex-exe", type=Path)
    parser.add_argument("--work-root", type=Path)
    args = parser.parse_args()

    require(platform.system() == "Windows", "This verification is Windows-only")
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Run only in GitHub Actions")
    require(os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted", "Run only on an ephemeral GitHub-hosted runner")
    github_sha = os.environ.get("GITHUB_SHA") or ""
    require(bool(re.fullmatch(r"[0-9a-fA-F]{40}", github_sha)), "GITHUB_SHA is missing or malformed")
    archive = args.plugin_zip.resolve()
    require(archive.is_file(), f"Plugin archive is missing: {archive}")
    sidecar_digest = verify_candidate_sidecar(archive)
    runner_temp = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    user_profile = Path(os.environ["USERPROFILE"])
    for path in (user_profile / ".agents" / "skills", user_profile / ".codex", user_profile / ".agents" / "plugins"):
        require(not path.exists(), f"GitHub runner is not clean: {path} exists")
    root = args.work_root.resolve() if args.work_root else runner_temp / "report-skills-release-verification"
    require(not root.exists(), "Verification work root already exists")
    root.mkdir(parents=True)
    workspace = root / "workspace"
    workspace.mkdir()
    temp = root / "tmp"
    temp.mkdir()
    codex_home = root / "codex-home"
    codex_home.mkdir()
    extracted = root / "extracted"
    codex = (args.codex_exe.resolve() if args.codex_exe else root / "codex-aarch64-pc-windows-msvc.exe")
    wrapper_root = root / "marketplace"
    env = make_environment(workspace, codex_home, temp)

    if args.codex_exe is None:
        download_codex(codex)
    else:
        require(codex.is_file(), f"Codex executable is missing: {codex}")
        require(sha256_file(codex) == CODEX_SHA256, "Codex executable digest mismatch")

    plugin_inventory_items = plugin_inventory()
    inventory_paths = [item.path.as_posix() for item in plugin_inventory_items]
    trusted_hashes = hash_inventory(REPO_ROOT, plugin_inventory_items)
    version_info = plugin_manifest_from_archive(archive)
    version = version_info.get("version")
    require(isinstance(version, str) and SEMVER_RE.fullmatch(version) is not None, f"Plugin version is not a safe semver value: {version!r}")
    require(version_info.get("name") == "report-skills", "Plugin identity mismatch")
    artifact = verify_archive(
        archive,
        "RELEASE_MANIFEST.json",
        inventory_paths,
        version,
        None,
        expected_source_hashes=trusted_hashes,
    )
    require(artifact["sha256"] == sidecar_digest, "Verified archive does not match sidecar digest")

    version_result = run_command([codex, "--version"], cwd=workspace, env=env, timeout=60)
    require(version_result.stdout.decode().strip() == "codex-cli 0.166.0", "Installed Codex CLI version mismatch")

    extract_verified_plugin(archive, extracted)
    extracted_inventory = tree_hash_inventory(extracted, archive)
    skills_root = extracted / "skills"
    expected_skills = sorted(
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    require(len(expected_skills) == 11, f"Expected eleven skills in candidate, got {len(expected_skills)}")
    wrapper = create_wrapper(extracted, wrapper_root)
    wrapper_inventory = tree_hash_inventory(Path(wrapper["payload_root"]), archive)
    wrapper_path = Path(wrapper["root"])
    catalog_path = Path(wrapper["catalog"])
    payload_path = Path(wrapper["payload_root"])

    register = run_command(
        [codex, "plugin", "marketplace", "add", str(wrapper_path), "--json"],
        cwd=workspace,
        env=env,
        timeout=120,
    )
    registration = json.loads(register.stdout.decode("utf-8"))
    require(registration.get("marketplaceName") == "report-skills-local", "Marketplace name mismatch")
    require(normalize_for_compare(registration.get("installedRoot")) == normalize_for_compare(wrapper_path), "Registered wrapper root mismatch")

    list_marketplaces = run_command(
        [codex, "plugin", "marketplace", "list"],
        cwd=workspace,
        env=env,
        timeout=60,
    )
    require("report-skills-local" in list_marketplaces.stdout.decode("utf-8"), "Marketplace was not listed")

    available_output = run_command(
        [codex, "plugin", "list", "--marketplace", "report-skills-local", "--available", "--json"],
        cwd=workspace,
        env=env,
        timeout=60,
    ).stdout.decode("utf-8")
    available = json.loads(available_output)
    require(available.get("installed") == [], "Candidate was unexpectedly installed before registration")
    available_plugins = available.get("available", [])
    require(len(available_plugins) == 1, "Expected exactly one available Report Skills entry")
    available_plugin = available_plugins[0]
    require(
        normalize_for_compare((available_plugin.get("source") or {}).get("path")) == normalize_for_compare(wrapper["payload_root"]),
        "Available plugin source is not the freshly wrapped candidate payload",
    )
    require(
        normalize_for_compare((available_plugin.get("marketplaceSource") or {}).get("source")) == normalize_for_compare(wrapper["root"]),
        "Available plugin marketplace is not the freshly created wrapper root",
    )
    require(
        available_plugin.get("pluginId") == "report-skills@report-skills-local"
        and available_plugin.get("version") == version
        and available_plugin.get("name") == "report-skills",
        "Available plugin identity mismatch",
    )

    install_result = run_command(
        [codex, "plugin", "add", "report-skills@report-skills-local", "--json"],
        cwd=workspace,
        env=env,
        timeout=120,
    )
    install_output = install_result.stdout.decode("utf-8")
    install_records = json_documents(install_result.stdout)
    require(len(install_records) >= 1, "Install command returned no JSON")
    installed_output = run_command(
        [codex, "plugin", "list", "--marketplace", "report-skills-local", "--json"],
        cwd=workspace,
        env=env,
        timeout=60,
    ).stdout.decode("utf-8")
    installed = json.loads(installed_output)
    if len(install_records) == 2:
        require(install_records[1] == installed, "Fresh installed listing disagrees with install command output")
    installed_plugins = installed.get("installed", [])
    require(len(installed_plugins) == 1, "Expected exactly one installed Report Skills plugin")
    installed_plugin = installed_plugins[0]
    require(
        normalize_for_compare((installed_plugin.get("source") or {}).get("path")) == normalize_for_compare(wrapper["payload_root"]),
        "Installed plugin source is not the freshly wrapped candidate payload",
    )
    require(
        normalize_for_compare((installed_plugin.get("marketplaceSource") or {}).get("source")) == normalize_for_compare(wrapper["root"]),
        "Installed plugin marketplace is not the freshly created wrapper root",
    )
    require(
        installed_plugin.get("pluginId") == "report-skills@report-skills-local"
        and installed_plugin.get("version") == version
        and installed_plugin.get("installed") is True
        and installed_plugin.get("enabled") is True,
        f"Installed plugin is not the enabled {version} candidate",
    )

    skills_result = skills_list(codex, cwd=workspace, env=env, client_version=version)
    data = skills_result.get("data")
    require(isinstance(data, list) and len(data) == 1, "skills/list returned an unexpected cwd count")
    discovery = data[0]
    require(discovery.get("errors") == [], f"skills/list returned errors: {discovery.get('errors')}")
    skills = discovery.get("skills")
    require(isinstance(skills, list), "skills/list did not return a skill list")

    discovered_paths: list[str] = []
    for skill in skills:
        require(isinstance(skill, dict), "skills/list returned a non-object skill entry")
        path_text = skill.get("path")
        require(isinstance(path_text, str), "Discovered skill is missing a path")
        discovered_paths.append(normalize_for_compare(path_text))
        require(skill.get("enabled") is True, f"Discovered skill is disabled: {skill.get('name')}")

    path_set = set(discovered_paths)
    require(len(path_set) == len(discovered_paths), "skills/list returned duplicate paths")
    codex_root = normalize_for_compare(codex_home)
    for path in path_set:
        require(
            path == codex_root or path.startswith(codex_root + os.sep),
            f"skills/list returned a path outside the fresh isolated CODEX_HOME: {path}",
        )

    install_first = install_records[0] if isinstance(install_records, list) and install_records else {}
    require(isinstance(install_first, dict) and install_first.get("pluginId") == "report-skills@report-skills-local", "Install response did not report the expected plugin identity")
    installed_root_text = install_first.get("installedPath")
    require(isinstance(installed_root_text, str) and installed_root_text, "Install response omitted installedPath")
    installed_root = Path(installed_root_text).resolve()
    target_names = {f"report-skills:{name}" for name in expected_skills}
    target_records = []
    for skill in skills:
        if isinstance(skill, dict) and skill.get("pluginId") == "report-skills@report-skills-local":
            target_records.append(skill)
    require(
        {skill.get("name") for skill in target_records} == target_names,
        f"skills/list target names did not match the eleven candidate skills: {[skill.get('name') for skill in target_records]}",
    )
    installed_inventory = tree_hash_inventory(installed_root, archive)
    expected_target_paths = {
        normalize_for_compare(installed_root / "skills" / name / "SKILL.md")
        for name in expected_skills
    }
    actual_target_paths = {normalize_for_compare(skill["path"]) for skill in target_records}
    require(actual_target_paths == expected_target_paths, "skills/list target paths do not equal the installed cache paths")

    receipt: dict[str, object] = {
        "schema_version": 1,
        "method": "github_hosted_windows_arm_ephemeral_release_candidate_verification",
        "candidate": artifact,
        "plugin_manifest": version_info,
        "source_commit": github_sha.lower(),
        "runtime": {
            "platform": platform.platform(),
            "codex_cli": "0.166.0",
            "codex_asset_sha256": CODEX_SHA256,
            "codex_home": str(codex_home),
            "runner_temporary": str(temp),
        },
        "marketplace": wrapper,
        "registration": registration,
        "payload_verification": {
            "archive_entries": len(extracted_inventory),
            "extracted_hashes_match": True,
            "wrapper_hashes_match": True,
            "installed_cache_hashes_match": True,
            "installed_cache_file_count": len(installed_inventory),
        },
        "available_plugin": available_plugin,
        "installed_plugin": installed_plugin,
        "model_free_discovery": {
            "wire_methods": ["initialize", "initialized", "skills/list"],
            "activation_not_claimed": True,
            "model_calls_requested": 0,
            "total_discovered_skills": len(skills),
            "target_skill_count": len(target_records),
            "expected_target_skill_names": sorted(target_names),
            "discovered_skill_paths": sorted(path_set),
            "errors": discovery.get("errors") or [],
            "stderr_excerpt": skills_result.get("_stderr_excerpt", ""),
        },
        "release_publication_authorized": False,
        "official_plugin_validator": "NOT RUN—unavailable in audited tooling",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json_bytes(receipt))
    print(
        json.dumps(
            {
                "status": "VERIFIED",
                "output": str(args.output.resolve()),
                "sha256": sha256_file(args.output),
                "plugin_zip_sha256": artifact["sha256"],
                "skills_discovered": len(skills),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
