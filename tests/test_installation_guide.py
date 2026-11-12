from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "docs" / "installation.md"


class InstallationGuideTests(unittest.TestCase):
    def documented_catalog(self, language: str) -> dict:
        guide = GUIDE.read_text(encoding="utf-8")
        blocks = re.findall(r"^```" + re.escape(language) + r"\s*\n(.*?)^```", guide, re.MULTILINE | re.DOTALL)
        for block in blocks:
            payloads = re.findall(r"@'\r?\n(.*?)\r?\n'@", block, re.DOTALL)
            payloads += re.findall(r"<<'JSON'\r?\n(.*?)\r?\nJSON(?:\r?\n|$)", block, re.DOTALL)
            for payload in payloads:
                candidate = json.loads(payload)
                if candidate.get("name") == "report-skills-local":
                    return candidate
        self.fail(f"Installation guide needs a complete manual {language} marketplace catalog")

    def assert_catalog_resolves_packaged_plugin(self, catalog: dict) -> None:
        self.assertEqual(len(catalog["plugins"]), 1)
        entry = catalog["plugins"][0]
        self.assertEqual(entry["name"], "report-skills")
        self.assertEqual(entry["source"]["source"], "local")
        relative = entry["source"]["path"]
        self.assertTrue(relative.startswith("./"))
        self.assertFalse(PurePosixPath(relative).is_absolute())
        self.assertNotIn("..", PurePosixPath(relative).parts)
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(entry["category"], "Productivity")
        with tempfile.TemporaryDirectory(prefix="guide-layout-") as temp:
            root = Path(temp)
            plugin = root / "plugins" / "report-skills"
            shutil.copytree(REPO_ROOT / ".codex-plugin", plugin / ".codex-plugin")
            shutil.copytree(REPO_ROOT / "skills", plugin / "skills")
            catalog_file = root / ".agents" / "plugins" / "marketplace.json"
            catalog_file.parent.mkdir(parents=True)
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
            # Codex resolves this relative to the marketplace root, not the
            # nested catalog directory. This checks the documented layout;
            # it does not claim that a host installation was performed.
            resolved = (catalog_file.parents[2] / relative).resolve()
            self.assertEqual(resolved, plugin.resolve())
            self.assertEqual(
                (resolved / ".codex-plugin" / "plugin.json").read_bytes(),
                (REPO_ROOT / ".codex-plugin" / "plugin.json").read_bytes(),
            )
            self.assertEqual(
                sorted(p.parent.name for p in (resolved / "skills").glob("*/SKILL.md")),
                sorted(p.parent.name for p in (REPO_ROOT / "skills").glob("*/SKILL.md")),
            )

    def test_windows_manual_catalog_resolves_the_packaged_plugin(self) -> None:
        self.assert_catalog_resolves_packaged_plugin(self.documented_catalog("powershell"))

    def test_posix_manual_catalog_matches_the_windows_layout(self) -> None:
        catalog = self.documented_catalog("bash")
        self.assert_catalog_resolves_packaged_plugin(catalog)
        self.assertEqual(catalog, self.documented_catalog("powershell"))

    def test_manual_route_does_not_require_the_creator_skill(self) -> None:
        guide = GUIDE.read_text(encoding="utf-8")
        prerequisites = guide.split("## Before you begin", 1)[1].split("## Windows", 1)[0]
        self.assertNotIn("The built-in `$plugin-creator` skill.", prerequisites)
        manual = guide.split("## Add the plugin to a personal marketplace", 1)[1].split(
            "### Optional creator-assisted setup", 1
        )[0]
        for command in (
            "codex plugin marketplace add",
            "codex plugin marketplace list",
            "codex plugin list --marketplace report-skills-local --available --json",
        ):
            self.assertIn(command, manual)
        cli = guide.split("### Codex CLI\n", 1)[1].split("## Test the installation", 1)[0]
        self.assertIn("codex plugin add report-skills@report-skills-local --json", cli)
        self.assertIn("codex plugin list --marketplace report-skills-local --json", cli)

    def test_registration_uses_the_printed_wrapper_root_without_a_default_fallback(self) -> None:
        guide = GUIDE.read_text(encoding="utf-8")
        registration = guide.split("### Register the manual marketplace", 1)[1].split(
            "### Optional creator-assisted setup", 1
        )[0]
        blocks = re.findall(
            r"^```(powershell|bash)\s*\n(.*?)^```",
            registration,
            re.MULTILINE | re.DOTALL,
        )
        self.assertCountEqual([language for language, _ in blocks], ["powershell", "bash"])
        for language, block in blocks:
            with self.subTest(language=language):
                self.assertIn("PASTE_THE_ABSOLUTE_MARKETPLACE_ROOT_HERE", block)
                preflight = block.split("codex plugin marketplace add", 1)[0]
                self.assertIn(".agents/plugins/marketplace.json", preflight)
                self.assertIn("plugins/report-skills/.codex-plugin/plugin.json", preflight)
                self.assertNotIn("Join-Path $env:USERPROFILE", preflight)
                self.assertNotIn("$HOME/report-skills-marketplace", preflight)
                root_variable = "$marketplaceRoot" if language == "powershell" else "$marketplace_root"
                registration_commands = [
                    line.strip() for line in block.splitlines()
                    if line.lstrip().startswith("codex plugin marketplace add ")
                ]
                self.assertEqual(
                    registration_commands,
                    [f'codex plugin marketplace add "{root_variable}" --json'],
                )


if __name__ == "__main__":
    unittest.main()
