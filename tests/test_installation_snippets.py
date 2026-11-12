"""Execute documented file-creation and registration-preflight snippets only.

These fixtures never call Codex, register a marketplace, install a plugin or
prove actual host/platform support. A Bash run on Windows remains a Windows run.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "docs" / "installation.md"


def file_inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class InstallationSnippetTests(unittest.TestCase):
    def assert_documented_fixture(self, language: str) -> None:
        cygpath = None
        if language == "powershell":
            executable = shutil.which("pwsh") or shutil.which("powershell.exe")
            if executable is None:
                self.skipTest("No PowerShell runtime is available for the documented snippet")
            argv = [executable, "-NoProfile", "-NonInteractive", "-Command"]
        elif os.name == "nt":
            git = shutil.which("git")
            if git is None:
                self.skipTest("Git Bash is unavailable")
            git_root = Path(git).resolve().parents[1]
            executable = git_root / "bin" / "bash.exe"
            cygpath = git_root / "usr" / "bin" / "cygpath.exe"
            if not executable.is_file() or not cygpath.is_file():
                self.skipTest("Native Git Bash and cygpath are unavailable")
            argv = [str(executable), "--noprofile", "--norc", "-c"]
        else:
            executable = shutil.which("bash")
            if executable is None:
                self.skipTest("Bash is unavailable")
            argv = [executable, "--noprofile", "--norc", "-c"]

        def shell_path(path: Path) -> str:
            if language == "powershell" or cygpath is None:
                return path.as_posix()
            return subprocess.check_output(
                [str(cygpath), "-u", str(path)], text=True, encoding="utf-8"
            ).strip()

        guide = GUIDE.read_text(encoding="utf-8")
        blocks = re.findall(
            r"^```" + language + r"\s*\n(.*?)^```", guide, re.MULTILINE | re.DOTALL
        )
        setup = next(
            block for block in blocks
            if "$catalogJson = @'" in block or 'cat > "$catalog_path"' in block
        )
        registration_section = guide.split("### Register the manual marketplace", 1)[1].split(
            "### Optional creator-assisted setup", 1
        )[0]
        registration = re.search(
            r"^```" + language + r"\s*\n(.*?)^```",
            registration_section,
            re.MULTILINE | re.DOTALL,
        ).group(1)
        self.assertNotIn("codex plugin", setup)
        # Only execute the validation/selection prefix. Never invoke Codex.
        preflight = registration.split("codex plugin marketplace add", 1)[0]
        self.assertNotIn("codex ", preflight)

        with tempfile.TemporaryDirectory(prefix="guide-exec-") as temp:
            root = Path(temp)
            source = root / "plugin [fixture] with spaces"
            source.mkdir()
            for folder in (".codex-plugin", ".zcode-plugin", "skills"):
                shutil.copytree(REPO_ROOT / folder, source / folder)
            shutil.copy2(REPO_ROOT / "marketplace.json", source / "marketplace.json")
            original = file_inventory(source)
            profile = root / "profile"
            profile.mkdir()
            env = dict(os.environ, USERPROFILE=str(profile), HOME=shell_path(profile))
            if cygpath is not None:
                env["PATH"] = "/usr/bin:/bin"

            def execute(script: str, environment: dict = env):
                return subprocess.run(
                    [*argv, script], cwd=root, env=environment, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=60,
                )

            # Model a reader choosing a fresh location after finding an older
            # default wrapper. The catalog and payload must remain paired.
            alternate_setup = setup.replace("report-skills-marketplace", "alternate wrapper")
            alternate_setup = alternate_setup.replace(
                "PASTE_THE_ABSOLUTE_EXTRACTED_PATH_HERE", shell_path(source)
            )
            created = execute(alternate_setup)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            wrapper = profile / "alternate wrapper"
            self.assertEqual(file_inventory(wrapper / "plugins/report-skills"), original)
            self.assertEqual(file_inventory(source), original)
            catalog = wrapper / ".agents/plugins/marketplace.json"
            self.assertFalse(catalog.read_bytes().startswith(b"\xef\xbb\xbf"))

            saved = file_inventory(wrapper)
            repeated = execute(alternate_setup)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(file_inventory(wrapper), saved)

            invalid_source = root / "invalid source"
            invalid_source.mkdir()
            other_profile = root / "other profile"
            other_profile.mkdir()
            other_env = dict(env, USERPROFILE=str(other_profile), HOME=shell_path(other_profile))
            rejected = execute(
                setup.replace("PASTE_THE_ABSOLUTE_EXTRACTED_PATH_HERE", shell_path(invalid_source)),
                other_env,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((other_profile / "report-skills-marketplace").exists())

            stale = profile / "report-skills-marketplace"
            shutil.copytree(wrapper, stale)
            (stale / "older-wrapper-marker.txt").write_text("old fixture\n", encoding="utf-8")
            selected = preflight.replace(
                "PASTE_THE_ABSOLUTE_MARKETPLACE_ROOT_HERE", shell_path(wrapper)
            )
            selected += (
                "\n[Console]::WriteLine('SELECTED_ROOT=' + $marketplaceRoot)\n"
                if language == "powershell" else
                "\nprintf 'SELECTED_ROOT=%s\\n' \"$marketplace_root\"\n"
            )
            observed = execute(selected)
            self.assertEqual(observed.returncode, 0, observed.stdout + observed.stderr)
            actual = re.search(r"^SELECTED_ROOT=(.+)$", observed.stdout, re.MULTILINE).group(1).strip()
            self.assertEqual(actual.replace("\\", "/"), shell_path(wrapper).replace("\\", "/"))
            self.assertEqual(file_inventory(wrapper), saved)

            invalid_root = root / "not a wrapper"
            invalid_root.mkdir()
            bad_preflight = execute(preflight.replace(
                "PASTE_THE_ABSOLUTE_MARKETPLACE_ROOT_HERE", shell_path(invalid_root)
            ))
            self.assertNotEqual(bad_preflight.returncode, 0)
            self.assertIn("completed wrapper root", bad_preflight.stdout + bad_preflight.stderr)

            for label, missing in (
                ("catalog", ".agents/plugins/marketplace.json"),
                ("manifest", "plugins/report-skills/.codex-plugin/plugin.json"),
            ):
                with self.subTest(missing=label):
                    partial = root / ("missing " + label)
                    shutil.copytree(wrapper, partial)
                    (partial / missing).unlink()
                    rejected_partial = execute(preflight.replace(
                        "PASTE_THE_ABSOLUTE_MARKETPLACE_ROOT_HERE", shell_path(partial)
                    ))
                    self.assertNotEqual(rejected_partial.returncode, 0)
                    self.assertIn(
                        "completed wrapper root",
                        rejected_partial.stdout + rejected_partial.stderr,
                    )

    def test_powershell_snippets_preserve_the_payload_and_alternate_root(self) -> None:
        self.assert_documented_fixture("powershell")

    def test_bash_snippets_preserve_the_payload_and_alternate_root(self) -> None:
        self.assert_documented_fixture("bash")


if __name__ == "__main__":
    unittest.main()
