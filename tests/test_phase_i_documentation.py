"""Publication-facing documentation and bundled-contract regressions."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PhaseIDocumentationTests(unittest.TestCase):
    def test_shared_alias_safe_guidance_is_bundled_for_every_skill(self):
        source = ROOT / "source" / "shared" / "validation-conventions.md"
        text = source.read_text(encoding="utf-8")
        self.assertIn("descriptive multi-word helper names", text)
        self.assertIn("define and invoke each helper in the same script", text)
        self.assertIn("& ${function:Get-LocalArtifactDigest} $path", text)
        self.assertIn("do not inspect or change aliases or consult command/session history", text)
        skills = json.loads((ROOT / "source" / "skill-map.yaml").read_text(encoding="utf-8"))["skills"]
        self.assertEqual(len(skills), 11)
        for skill in skills:
            with self.subTest(skill=skill):
                self.assertEqual((ROOT / "skills" / skill / "references" / "validation-conventions.md").read_bytes(), source.read_bytes())
    def test_current_release_scope_is_consistent_across_public_documents(self):
        required = {
            "README.md": ("NOT RUN—unavailable in audited tooling", "v0.2.0 GitHub-only"),
            "docs/release-checklist.md": ("For an optional RC only:", "Stable v0.2.0 does not require an additional RC."),
            "docs/evaluation.md": ("The published `v0.1.0` and `v0.2.0-rc.1` identities remain immutable.",),
            "docs/installation.md": ("The approved v0.2.0 verification target is Codex on Windows plus standalone packages.", "documented but unverified"),
        }
        missing = []
        for name, fragments in required.items():
            text = (ROOT / name).read_text(encoding="utf-8")
            missing.extend((name, fragment) for fragment in fragments if fragment not in text)
        self.assertEqual(missing, [])
    def test_bundled_helper_runtime_requirements_and_safe_fallback_are_explicit(self):
        documents = (
            "source/skills/evidence-first-report/SKILL.md",
            "source/skills/editorial-data-storytelling/SKILL.md",
            "source/skills/report-content-repurposer/SKILL.md",
            "docs/installation.md",
        )
        missing = [name for name in documents if "PowerShell 7 (`pwsh`)" not in (ROOT / name).read_text(encoding="utf-8")]
        installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
        for fragment in ("Windows PowerShell 5.1", "do not install", "Python 3.11"):
            if fragment not in installation:
                missing.append("docs/installation.md: " + fragment)
        self.assertEqual(missing, [])
    def test_bundled_examples_match_the_router_and_visual_qa_contracts(self):
        workflow = (ROOT / "templates" / "workflow-manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("\nexternal_actions: []\n", "\n" + workflow)
        self.assertIn("\npublication_authorized: false", "\n" + workflow)
        protocol = (ROOT / "source" / "skills" / "visual-hygiene-auditor" / "references" / "three-pass-audit-protocol.md").read_text(encoding="utf-8")
        self.assertIn("## Pass 3: reader-comprehension", protocol)
        example = protocol.split("```yaml", 1)[1].split("```", 1)[0]
        self.assertRegex(example, r"(?m)^impact: .+$")
        self.assertEqual((ROOT / "skills" / "report-skills" / "assets" / "templates" / "workflow-manifest.yaml").read_text(encoding="utf-8"), workflow)
        self.assertEqual((ROOT / "skills" / "visual-hygiene-auditor" / "references" / "three-pass-audit-protocol.md").read_text(encoding="utf-8"), protocol)
    def test_local_readiness_repairs_are_documented_without_a_release_pass(self):
        text = (ROOT / "docs" / "release-preparation.md").read_text(encoding="utf-8")
        current = text.split("## Current local readiness update (v60)", 1)[1].split("## Blocker register", 1)[0]
        for fragment in ("PowerShell `.ps1`", "exact Git blobs", "row count", "field-for-field", "strict UTF-8", "same decoded snapshot", "not universal CSV equivalence", "requires combined full-suite and independent-review gates"):
            self.assertIn(fragment, current)

    def test_active_host_guard_scope_and_limits_are_documented(self):
        text = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
        for fragment in ("task-output-and-host-boundary-safety-v13", "Get-Process", "not a general shell parser", "conservative false positives"):
            self.assertIn(fragment, text)

    def test_windows_ci_requires_and_runs_the_helper_regressions(self):
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        required = ("shutil.which('pwsh')", "tests.test_task_shell_helpers", "tests.test_phase_i_csv_contracts", "tests.test_phase_i_powershell_csv_parity", "tests.test_phase_i_process_guard", "tests.test_phase_i_review_csv_regressions", "tests.test_skill_csv_writer", "tests.test_skill_portability")
        self.assertEqual([name for name in required if name not in workflow], [])


if __name__ == "__main__":
    unittest.main()
