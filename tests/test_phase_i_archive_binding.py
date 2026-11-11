"""Independent release verification against synthetic, immutable Git blob bytes.

No release builder, evaluated model, or real repository mutation is needed.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
PLUGIN_MANIFEST = "RELEASE_MANIFEST.json"
SOURCE_MANIFEST = "SOURCE_SNAPSHOT_MANIFEST.json"


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ArchiveSourceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = load_script("phase_i_archive_inventory", "release_inventory.py")
        self.module_patch = mock.patch.dict(sys.modules, {"release_inventory": self.inventory})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.release = load_script("phase_i_archive_release", "create_release_package.py")
        self.verifier = load_script("phase_i_archive_verifier", "verify_release_artifacts.py")
        self.create_patch = mock.patch.dict(sys.modules, {"create_release_package": self.release})
        self.create_patch.start()
        self.addCleanup(self.create_patch.stop)
        temporary = tempfile.TemporaryDirectory(prefix="phase-i-archive-synthetic-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "synthetic-source"
        self.directory = self.root / "synthetic-archives"
        self.repo.mkdir()
        self.directory.mkdir()
        self.payloads = {
            path: f"synthetic public file: {path}\n".encode("utf-8")
            for path in (*self.release.ROOT_FILES, *self.release.DOC_FILES)
        }
        self.payloads.update({
            ".codex-plugin/plugin.json": json.dumps({"version": VERSION}).encode("utf-8"),
            ".zcode-plugin/plugin.json": b'{"name":"synthetic"}\r\n',
            "marketplace.json": b'{"plugins":[]}\n',
            "skills/example/SKILL.md": b"synthetic skill\r\n",
            "scripts/source-only.py": b"#!/usr/bin/env python3\r\nprint('synthetic')\r\n",
            "source/opaque.bin": b"\x00\xff\x80\r\n\x00",
        })
        metadata_path = self.repo / ".codex-plugin" / "plugin.json"
        metadata_path.parent.mkdir()
        metadata_path.write_bytes(self.payloads[".codex-plugin/plugin.json"])
        # Model ls-tree and cat-file independently of mutable worktree paths.
        self.object_ids = {
            path: hashlib.sha1(
                b"blob " + str(len(content)).encode("ascii") + b"\0" + content
            ).hexdigest()
            for path, content in self.payloads.items()
        }
        self.blobs = {self.object_ids[path]: content for path, content in self.payloads.items()}
        self.tree = b"".join(
            (
                f"{'100755' if path.endswith('.py') else '100644'} blob "
                f"{self.object_ids[path]}\t{path}\0"
            ).encode("utf-8")
            for path in sorted(self.payloads)
        )
        self.git_calls: list[tuple[str, ...]] = []
        self.status = b""
        self.unreadable_blobs: set[str] = set()
        for module in (self.verifier, self.release):
            patcher = mock.patch.object(module, "REPO_ROOT", self.repo)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(self.verifier, "PLUGIN_MANIFEST", metadata_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(self.inventory, "_run_git", side_effect=self.fake_git)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_archives()

    def fake_git(self, repo_root: Path, *arguments: str, text: bool = False):
        self.assertEqual(repo_root.resolve(), self.repo.resolve())
        self.git_calls.append(arguments)
        returncode = 0
        if arguments == ("rev-parse", "--show-toplevel"):
            stdout = str(self.repo.resolve()) + "\n"
            self.assertTrue(text)
        elif arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            stdout = self.status
        elif arguments == ("ls-tree", "-r", "-z", "HEAD"):
            stdout = self.tree
        elif len(arguments) == 3 and arguments[:2] == ("cat-file", "blob"):
            object_id = arguments[2]
            self.assertIn(object_id, self.blobs)
            returncode = 1 if object_id in self.unreadable_blobs else 0
            stdout = b"" if returncode else self.blobs[object_id]
        else:
            raise AssertionError(f"Unexpected synthetic Git request: {arguments}")
        return subprocess.CompletedProcess(arguments, returncode, stdout, "" if text else b"")

    def selected_plugin_payloads(self) -> dict[str, bytes]:
        return {
            name: content for name, content in self.payloads.items()
            if PurePosixPath(name) in self.release.PUBLIC_FILES
            or name.split("/", 1)[0] in self.release.PLUGIN_PREFIXES
        }

    def write_archive(
        self,
        manifest_name: str,
        payloads: dict[str, bytes],
        *,
        authorized_tag: str | None = None,
        manifest_updates: dict | None = None,
    ) -> Path:
        is_plugin = manifest_name == PLUGIN_MANIFEST
        archive_name = (
            f"report-skills-{VERSION}.zip" if is_plugin else f"report-skills-source-{VERSION}.zip"
        )
        archive = self.directory / archive_name
        manifest = {
            "schema_version": 1,
            "version": VERSION,
            "external_publication_authorized": bool(authorized_tag),
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()},
        }
        if is_plugin:
            manifest.update({
                "plugin": "report-skills",
                "publication_state": "approved-public-candidate" if authorized_tag else "local-candidate",
            })
        else:
            manifest.update({
                "project": "report-skills",
                "snapshot_type": "intended-public-repository-tree",
                "git_history_present": False,
                "publication_state": (
                    "approved-public-source-candidate" if authorized_tag else "local-source-candidate"
                ),
                "file_count": len(payloads),
            })
        if authorized_tag:
            manifest["authorized_release_tag"] = authorized_tag
        if manifest_updates is not None:
            manifest.update(manifest_updates)
        entries = {**payloads, manifest_name: json.dumps(manifest, sort_keys=True).encode("utf-8")}
        with zipfile.ZipFile(archive, "w") as output:
            for name, content in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                output.writestr(info, content)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix(".zip.sha256").write_text(
            f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n"
        )
        return archive

    def write_archives(self, *, authorized_tag: str | None = None) -> None:
        self.write_archive(PLUGIN_MANIFEST, self.selected_plugin_payloads(), authorized_tag=authorized_tag)
        self.write_archive(SOURCE_MANIFEST, dict(self.payloads), authorized_tag=authorized_tag)

    def run_verifier(self, *, compare_directory: Path | None = None, authorized_tag: str | None = None):
        args = self.verifier.argparse.Namespace(
            directory=self.directory,
            compare_directory=compare_directory,
            authorized_release_tag=authorized_tag,
        )
        stdout = io.StringIO()
        with mock.patch.object(self.verifier, "parse_args", return_value=args), contextlib.redirect_stdout(stdout):
            result = self.verifier.main()
        self.assertEqual(result, 0)
        return json.loads(stdout.getvalue())

    def test_exact_synthetic_blob_payloads_pass_for_both_archives(self) -> None:
        receipt = self.run_verifier()
        self.assertEqual([asset["manifest"] for asset in receipt["assets"]], [PLUGIN_MANIFEST, SOURCE_MANIFEST])
        self.assertEqual(
            [asset["entry_count"] for asset in receipt["assets"]],
            [len(self.selected_plugin_payloads()) + 1, len(self.payloads) + 1],
        )
        self.assertTrue(all(not asset["publication_authorized"] for asset in receipt["assets"]))

    def test_rewritten_payload_manifest_and_sidecar_cannot_replace_trusted_blob(self) -> None:
        for manifest_name in (PLUGIN_MANIFEST, SOURCE_MANIFEST):
            with self.subTest(manifest=manifest_name):
                self.write_archives()
                self.run_verifier()  # The identical fixture must pass before a single payload changes.
                payloads = (
                    self.selected_plugin_payloads() if manifest_name == PLUGIN_MANIFEST else dict(self.payloads)
                )
                payloads["README.md"] = b"replaced source with a matching archive-authored hash\n"
                archive = self.write_archive(manifest_name, payloads)
                sidecar = archive.with_suffix(".zip.sha256")
                self.assertEqual(self.verifier.verify_sidecar(archive, sidecar), hashlib.sha256(archive.read_bytes()).hexdigest())
                with self.assertRaisesRegex(SystemExit, "Trusted source.*hash mismatch: README[.]md"):
                    self.run_verifier()

    def test_every_selected_payload_is_bound_to_its_exact_raw_blob(self) -> None:
        for manifest_name in (PLUGIN_MANIFEST, SOURCE_MANIFEST):
            self.write_archives()
            self.run_verifier()
            original = self.selected_plugin_payloads() if manifest_name == PLUGIN_MANIFEST else self.payloads
            for name, content in original.items():
                with self.subTest(manifest=manifest_name, path=name):
                    self.write_archives()
                    changed = {**original, name: content + b"\x00synthetic byte mutation\xff"}
                    self.write_archive(manifest_name, changed)
                    with self.assertRaisesRegex(SystemExit, "Trusted source blob hash mismatch: " + re.escape(name)):
                        self.run_verifier()

    def test_worktree_bytes_do_not_replace_exact_selected_blobs(self) -> None:
        self.run_verifier()
        changed = b"mutable worktree representation\r\n"
        (self.repo / "README.md").write_bytes(changed)
        # Clean Git status can coexist with filtered/normalized worktree bytes.
        self.run_verifier()
        payloads = {**self.selected_plugin_payloads(), "README.md": changed}
        self.write_archive(PLUGIN_MANIFEST, payloads)
        with self.assertRaisesRegex(SystemExit, "Trusted source blob hash mismatch: README[.]md"):
            self.run_verifier()

    def test_hash_reads_use_exact_object_ids_and_preserve_raw_bytes(self) -> None:
        self.run_verifier()
        reads = [arguments for arguments in self.git_calls if arguments[:2] == ("cat-file", "blob")]
        expected_ids = [self.object_ids[name] for name in sorted(self.selected_plugin_payloads())]
        expected_ids.extend(self.object_ids[name] for name in sorted(self.payloads))
        self.assertEqual([arguments[2] for arguments in reads], expected_ids)
        selected = self.inventory.tracked_head_inventory(self.repo)
        self.assertEqual(
            self.inventory.hash_inventory(self.repo, iter(selected)),
            {name: hashlib.sha256(content).hexdigest() for name, content in self.payloads.items()},
        )

    def test_selected_object_id_mutation_invalidates_previous_archive(self) -> None:
        self.run_verifier()
        old_id = self.object_ids["README.md"]
        new_id = self.object_ids["scripts/source-only.py"]
        self.tree = self.tree.replace(old_id.encode("ascii"), new_id.encode("ascii"))
        with self.assertRaisesRegex(SystemExit, "Trusted source blob hash mismatch: README[.]md"):
            self.run_verifier()

    def test_missing_and_extra_payloads_cannot_rewrite_expected_inventories(self) -> None:
        for manifest_name in (PLUGIN_MANIFEST, SOURCE_MANIFEST):
            for mutation in ("missing", "extra"):
                with self.subTest(manifest=manifest_name, mutation=mutation):
                    self.write_archives()
                    self.run_verifier()
                    payloads = (
                        self.selected_plugin_payloads() if manifest_name == PLUGIN_MANIFEST else dict(self.payloads)
                    )
                    if mutation == "missing":
                        del payloads["README.md"]
                    else:
                        payloads["source/unselected.bin"] = b"synthetic unselected payload\n"
                    self.write_archive(manifest_name, payloads)
                    with self.assertRaisesRegex(SystemExit, "Trusted source inventory mismatch"):
                        self.run_verifier()

    def test_plugin_selection_does_not_expand_to_full_source_inventory(self) -> None:
        self.run_verifier()
        self.write_archive(PLUGIN_MANIFEST, dict(self.payloads))
        with self.assertRaisesRegex(SystemExit, "Trusted source inventory mismatch"):
            self.run_verifier()

    def test_trusted_hash_inventory_cannot_be_missing_extra_or_changed(self) -> None:
        payloads = self.selected_plugin_payloads()
        hashes = {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()}
        archive = self.directory / f"report-skills-{VERSION}.zip"

        def check(expected):
            return self.verifier.verify_archive(
                archive, PLUGIN_MANIFEST, payloads, VERSION, None, expected_source_hashes=expected
            )

        check(hashes)
        missing = {name: digest for name, digest in hashes.items() if name != "README.md"}
        extra = {**hashes, "source/unselected.bin": "0" * 64}
        for expected in (missing, extra):
            with self.subTest(inventory=sorted(expected)):
                with self.assertRaisesRegex(SystemExit, "Trusted source inventory mismatch"):
                    check(expected)
        for bad_hash in ("0" * 64, "", hashes["README.md"].upper(), None, 0):
            with self.subTest(hash_value=bad_hash):
                with self.assertRaisesRegex(SystemExit, "Trusted source blob hash mismatch: README[.]md"):
                    check({**hashes, "README.md": bad_hash})

    def test_unreadable_blob_has_no_worktree_or_source_manifest_fallback(self) -> None:
        self.run_verifier()
        (self.repo / "README.md").write_bytes(self.payloads["README.md"])
        (self.repo / SOURCE_MANIFEST).write_text(json.dumps({
            "schema_version": 1,
            "project": "report-skills",
            "snapshot_type": "intended-public-repository-tree",
            "git_history_present": False,
            "file_count": len(self.payloads),
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in self.payloads.items()},
        }), encoding="utf-8")
        self.unreadable_blobs.add(self.object_ids["README.md"])
        with self.assertRaisesRegex(SystemExit, "Unable to read tracked release blob: README[.]md"):
            self.run_verifier()

    def test_dirty_tree_is_rejected_before_blob_reads(self) -> None:
        self.run_verifier()
        self.git_calls.clear()
        self.status = b" M README.md\n"
        with self.assertRaisesRegex(SystemExit, "dirty release worktree"):
            self.run_verifier()
        self.assertFalse(any(call[:2] == ("cat-file", "blob") for call in self.git_calls))

    def test_trusted_head_path_and_mode_guards_remain_fail_closed(self) -> None:
        valid_tree = self.tree
        self.run_verifier()
        object_id = self.object_ids["README.md"]
        invalid_entries = (
            ("120000", "blob", "docs/link.md", "non-regular tracked release entry"),
            ("160000", "commit", "vendor/submodule", "non-regular tracked release entry"),
            ("100644", "blob", "EVALS/RUNS/raw.json", "tracked raw evaluation path"),
            ("100644", "blob", "EVALS/REVIEW/raw.json", "tracked raw evaluation path"),
            ("100644", "blob", "../outside.md", "unsafe tracked release path"),
            ("100644", "blob", "README.MD", "colliding tracked release paths"),
            ("100644", "blob", "Skills/other/SKILL.md", "colliding tracked release directory paths"),
        )
        for mode, object_type, name, message in invalid_entries:
            with self.subTest(mode=mode, name=name):
                self.tree = valid_tree + f"{mode} {object_type} {object_id}\t{name}\0".encode("utf-8")
                with self.assertRaisesRegex(SystemExit, message):
                    self.run_verifier()

    def test_archive_manifest_stays_independent_of_trusted_source_hashes(self) -> None:
        self.run_verifier()
        for manifest_name in (PLUGIN_MANIFEST, SOURCE_MANIFEST):
            with self.subTest(manifest=manifest_name):
                self.write_archives()
                payloads = self.selected_plugin_payloads() if manifest_name == PLUGIN_MANIFEST else dict(self.payloads)
                wrong_hashes = {
                    name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()
                }
                wrong_hashes["README.md"] = "0" * 64
                self.write_archive(manifest_name, payloads, manifest_updates={"files": wrong_hashes})
                with self.assertRaisesRegex(SystemExit, "Archive manifest hash mismatch: README[.]md"):
                    self.run_verifier()

    def test_sidecar_checksum_guard_still_rejects_drift(self) -> None:
        self.run_verifier()
        archive = self.directory / f"report-skills-{VERSION}.zip"
        archive.with_suffix(".zip.sha256").write_text(
            f"{'0' * 64}  {archive.name}\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SystemExit, "Checksum mismatch"):
            self.run_verifier()

    def test_comparison_assets_still_require_exact_byte_equality(self) -> None:
        comparison = self.root / "synthetic-comparison"
        shutil.copytree(self.directory, comparison)
        receipt = self.run_verifier(compare_directory=comparison)
        for name in receipt["asset_names"]:
            with self.subTest(asset=name):
                shutil.copyfile(self.directory / name, comparison / name)
                with (comparison / name).open("ab") as handle:
                    handle.write(b"synthetic comparison drift")
                with self.assertRaisesRegex(SystemExit, "Non-reproducible release asset: " + re.escape(name)):
                    self.run_verifier(compare_directory=comparison)
                shutil.copyfile(self.directory / name, comparison / name)

    def test_identical_forged_comparison_copy_cannot_establish_source_identity(self) -> None:
        self.run_verifier()
        changed = {**self.payloads, "README.md": b"synthetic forged source\n"}
        self.write_archive(SOURCE_MANIFEST, changed)
        comparison = self.root / "identical-forged-copy"
        shutil.copytree(self.directory, comparison)
        with self.assertRaisesRegex(SystemExit, "Trusted source blob hash mismatch: README[.]md"):
            self.run_verifier(compare_directory=comparison)

    def test_explicit_authorized_metadata_still_uses_the_same_blob_binding(self) -> None:
        tag = f"v{VERSION}"
        self.write_archives(authorized_tag=tag)
        receipt = self.run_verifier(authorized_tag=tag)
        self.assertEqual(receipt["authorized_release_tag"], tag)
        self.assertTrue(all(asset["publication_authorized"] for asset in receipt["assets"]))


class RawGitBlobInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = load_script("phase_i_real_blob_inventory", "release_inventory.py")
        temporary = tempfile.TemporaryDirectory(prefix="phase-i-archive-git-objects-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.git("init", "--quiet")

    def git(self, *arguments: str, payload: bytes | None = None) -> bytes:
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            input=payload,
            capture_output=True,
            check=True,
        ).stdout

    def test_raw_blob_hashes_preserve_crlf_binary_and_empty_bytes_without_a_commit(self) -> None:
        payloads = {
            "opaque.bin": b"\x00\xff\x80\r\n\x00",
            "helper.py": b"#!/usr/bin/env python3\r\nprint('synthetic')\r\n",
            "empty.txt": b"",
        }
        tree_entries = []
        for name, content in payloads.items():
            object_id = self.git("hash-object", "-w", "--stdin", payload=content).decode("ascii").strip()
            mode = "100755" if name.endswith(".py") else "100644"
            tree_entries.append(f"{mode} blob {object_id}\t{name}\0".encode("utf-8"))
            (self.repo / name).write_bytes(b"different mutable worktree bytes\n")
        inventory = self.inventory._parse_tree(b"".join(tree_entries))
        self.assertEqual(
            self.inventory.hash_inventory(self.repo, iter(inventory)),
            {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()},
        )

    def test_missing_git_blob_is_not_replaced_with_present_worktree_bytes(self) -> None:
        payload = b"synthetic source\r\n"
        object_id = self.git("hash-object", "-w", "--stdin", payload=payload).decode("ascii").strip()
        selected = self.inventory.TrackedFile(PurePosixPath("README.md"), "100644", object_id)
        (self.repo / "README.md").write_bytes(payload)
        self.assertEqual(
            self.inventory.hash_inventory(self.repo, [selected]),
            {"README.md": hashlib.sha256(payload).hexdigest()},
        )
        absent = self.inventory.TrackedFile(selected.path, selected.mode, "f" * 40)
        with self.assertRaisesRegex(SystemExit, "Unable to read tracked release blob: README[.]md"):
            self.inventory.hash_inventory(self.repo, [absent])


if __name__ == "__main__":
    unittest.main()
