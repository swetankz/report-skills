"""Paired PowerShell helper guidance and model-free regression controls."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_behavioral_benchmark as benchmark
import evaluation_common as ec

POWERSHELLS = sorted({
    executable
    for name in ("powershell.exe", "pwsh")
    if (executable := shutil.which(name)) is not None
})


def helper_example() -> str:
    prompt = benchmark.task_prompt({
        "configuration": "without_skill", "skill": "report-visual-system", "prompt": "Synthetic task",
    })
    match = re.search(r"`(& \$\{function:Get-LocalArtifactDigest\} \$path)`", prompt)
    if match is None:
        raise AssertionError("Missing explicit function-script-block invocation example")
    return match.group(1)


def run_synthetic_script(executable: str, script: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="rs-helper-") as folder:
        root = Path(folder)
        (root / "fixture").mkdir()
        (root / "fixture" / "input.txt").write_bytes(b"synthetic local input\n")
        result = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
        )
    if result.returncode != 0:
        raise AssertionError("Synthetic helper fixture failed: " + result.stderr.decode("utf-8", errors="replace")[:350])
    return json.loads(result.stdout.decode("utf-8-sig"))


class TaskShellHelperGuidanceTests(unittest.TestCase):
    def test_alias_safe_guidance_is_identical_in_both_configurations(self):
        common = []
        for configuration in ("with_skill", "without_skill"):
            prompt = benchmark.task_prompt({
                "configuration": configuration,
                "skill": "report-visual-system",
                "prompt": "Produce synthetic workspace-local artifacts.",
            })
            common.append(prompt.split("Configuration instruction:", 1)[0])
        self.assertEqual(common[0], common[1])
        self.assertIn("& ${function:Get-LocalArtifactDigest} $path", common[0])
        self.assertIn("descriptive multi-word helper names", common[0])
        self.assertIn("define and invoke each helper in the same script", common[0])
        self.assertIn("Do not inspect or change aliases or consult command/session history", common[0])

    def test_new_prompt_has_a_fresh_method_but_retains_the_guard_identity(self):
        self.assertEqual(ec.EVALUATION_METHOD_VERSION, "report-skills-release-evaluation-v62")
        self.assertEqual(ec.TASK_SKILL_BODY_READ_GUARD, "named-skill-path-command-events-v5")


@unittest.skipUnless(POWERSHELLS, "No native PowerShell runtime is available")
class NativeHelperInvocationTests(unittest.TestCase):
    def test_same_script_h_alias_collision_is_bypassed_without_changing_the_alias(self):
        # This is a fresh, empty synthetic process, not a claim about the failed run's history.
        script = r"""
$ErrorActionPreference = 'Stop'
$before = @(Get-History).Count
$aliasBefore = (Get-Alias -Name H).Definition
$script:helperCalls = 0
function H { param([string]$value) $script:helperCalls += 1; 'synthetic-' + $value }
$bareFailed = $false
$errorCommand = ''
try { H 123456789 -ErrorAction Stop | Out-Null }
catch { $bareFailed = $true; $errorCommand = $_.InvocationInfo.MyCommand.Name }
$value = & ${function:H} 'value'
[ordered]@{
    history_before = $before; history_after = @(Get-History).Count;
    alias_before = $aliasBefore; alias_after = (Get-Alias -Name H).Definition;
    bare_failed = $bareFailed; error_command = $errorCommand;
    helper_calls = $script:helperCalls; value = $value;
    psreadline_loaded = [bool](Get-Module -Name PSReadLine)
} | ConvertTo-Json -Compress
"""
        for executable in POWERSHELLS:
            with self.subTest(executable=executable):
                result = run_synthetic_script(executable, script)
                self.assertEqual(result["history_before"], 0)
                self.assertEqual(result["history_after"], 0)
                self.assertFalse(result["psreadline_loaded"])
                self.assertEqual(result["alias_before"], "Get-History")
                self.assertEqual(result["alias_after"], result["alias_before"])
                self.assertTrue(result["bare_failed"])
                self.assertEqual(result["error_command"], "Get-History")
                self.assertEqual(result["helper_calls"], 1)
                self.assertEqual(result["value"], "synthetic-value")

    def test_actual_prompt_example_hashes_only_the_synthetic_local_file(self):
        example = helper_example()
        self.assertEqual(example, "& ${function:Get-LocalArtifactDigest} $path")
        script = r"""
$ErrorActionPreference = 'Stop'
$script:helperCalls = 0
function Get-LocalArtifactDigest {
    param([string]$path)
    $script:helperCalls += 1
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    [System.BitConverter]::ToString($hash).Replace('-', '').ToLowerInvariant()
}
$path = 'fixture/input.txt'
$digest = """ + example + r"""
[ordered]@{digest = $digest; helper_calls = $script:helperCalls} | ConvertTo-Json -Compress
"""
        self.assertNotIn("Get-Command", script)
        self.assertNotIn("Get-Alias", script)
        self.assertNotIn("Get-History", script)
        for executable in POWERSHELLS:
            with self.subTest(executable=executable):
                result = run_synthetic_script(executable, script)
                self.assertEqual(result["helper_calls"], 1)
                self.assertEqual(result["digest"], hashlib.sha256(b"synthetic local input\n").hexdigest())


class UnchangedBoundaryGuardTests(unittest.TestCase):
    def test_explicit_helper_invocation_does_not_mask_independent_trace_violations(self):
        command = "function Get-LocalArtifactDigest { param($path) $path }; $path = 'fixture/input.txt'; " + helper_example()
        with tempfile.TemporaryDirectory(prefix="rs-helper-trace-") as folder:
            transcript = Path(folder) / "transcript.jsonl"

            def errors_for(text):
                transcript.write_text(json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": text}}) + "\n", encoding="utf-8")
                return ec.task_trace_isolation_validation_errors(transcript)

            self.assertEqual(errors_for(command), [])
            forbidden = (
                ("git status", "Git command"),
                ("Get-Content .git/HEAD", "Git metadata path"),
                ("Get-Content ../outside.txt", "parent path traversal"),
                ("Get-Command ruby", "host capability discovery"),
                ("Get-Process", "process inspection"),
                ("Get-ChildItem Env:", "environment enumeration"),
            )
            for suffix, expected in forbidden:
                with self.subTest(suffix=suffix):
                    self.assertTrue(any(expected in error for error in errors_for(command + "; " + suffix)))

    def test_reported_failed_history_attempt_remains_rejected(self):
        output = {"status": "completed", "summary": "Synthetic local output.", "artifacts": [], "integrity_events": [], "external_mutations": [], "workspace_boundary_accesses": [], "not_verified": []}
        with tempfile.TemporaryDirectory(prefix="rs-helper-audit-") as folder:
            path = Path(folder) / "task-output.json"
            path.write_text(json.dumps(output), encoding="utf-8")
            self.assertEqual(ec.task_output_safety_validation_errors(path), [])
            output["workspace_boundary_accesses"] = [{"operation": "attempted read", "target": "PowerShell session history, entry 123456789", "evidence": "Synthetic reported failed lookup."}]
            path.write_text(json.dumps(output), encoding="utf-8")
            self.assertEqual(ec.task_output_safety_validation_errors(path), ["task output records workspace-boundary access"])


if __name__ == "__main__":
    unittest.main()
