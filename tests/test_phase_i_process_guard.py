"""Offline Get-Process guard regressions; every command is unexecuted data."""
from __future__ import annotations

import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from evaluation_common import (  # noqa: E402
    TASK_OUTPUT_SAFETY_GUARD,
    TASK_SKILL_BODY_READ_GUARD,
    canonical_task_isolation_receipt,
    task_trace_isolation_validation_errors,
)


class PhaseIProcessGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.transcript = Path(temporary.name) / "synthetic-trace.jsonl"

    def errors_for(
        self, command: str, *, output: str = "", extra_items: tuple[dict, ...] = ()
    ) -> list[str]:
        # Exit/status/output are fixture data, not observed native results.
        items = ({
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": 0,
            "status": "completed",
        }, *extra_items)
        self.transcript.write_text(
            "".join(json.dumps({"type": "item.completed", "item": item}) + "\n" for item in items),
            encoding="utf-8",
        )
        return task_trace_isolation_validation_errors(self.transcript)

    @staticmethod
    def forms(command: str) -> tuple[str, str]:
        return command, f'"C:/runtime/pwsh.exe" -Command {shlex.quote(command)}'

    def assert_process_inspection(self, command: str) -> None:
        errors = self.errors_for(command)
        self.assertTrue(any("process inspection" in error for error in errors), errors)

    def test_bare_get_process_is_process_inspection(self) -> None:
        self.assertEqual(self.errors_for("Get-Content -LiteralPath fixture/input.txt"), [])
        self.assert_process_inspection("Get-Process")

    def test_ordinary_invocations_raw_and_serialized(self) -> None:
        commands = (
            "Get-Process",
            "gEt-PrOcEsS",
            "Get-Process -Name synthetic-worker",
            "Get-Process | Select-Object Id,ProcessName",
            "$items = Get-Process; $items.Count",
            "(Get-Process).Count",
            "& 'Get-Process'",
            ' & "Get-Process" ',
            "& ('Get-Process')",
            ". 'Get-Process'",
            "Microsoft.PowerShell.Management\\Get-Process",
            "& 'Microsoft.PowerShell.Management\\Get-Process'",
            "Write-Output 'Get-Process'; Get-Process",
            "Get-Process; Write-Output 'Get-Process'",
            "Write-Output ok | Get-Process",
            "if ($true) { Get-Process }",
            "Write-Output \"$(Get-Process)\"",
            "Invoke-Expression 'Get-Process'",
            "iex -Command 'Get-Process'",
        )
        for command in commands:
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assertEqual(self.errors_for("Get-Content -LiteralPath fixture/input.txt"), [])
                    self.assert_process_inspection(form)

    def test_keyword_prefixed_process_pipelines_raw_and_serialized(self) -> None:
        self.assertEqual(self.errors_for("Write-Output 'Get-Process'"), [])
        self.assert_process_inspection("Get-Process")
        commands = []
        for keyword in ("return", "throw", "exit", "ReTuRn", "ThRoW", "ExIt"):
            for invocation in (
                "Get-Process",
                "Get-Process | Select-Object Id",
                "Microsoft.PowerShell.Management\\Get-Process",
                "& 'Get-Process'",
                '& "Get-Process"',
                "& ('Get-Process')",
                ". 'Get-Process'",
                "& 'Microsoft.PowerShell.Management\\Get-Process'",
            ):
                commands.append(f"{keyword} {invocation}")
        for keyword in ("return", "throw", "exit"):
            commands.extend((
                f"function Get-Synthetic {{ {keyword} Get-Process }}; Get-Synthetic",
                "function Get-Synthetic { function Get-Nested { "
                f"{keyword} Get-Process }}; Get-Nested }}; Get-Synthetic",
                f"if ($true) {{ {keyword}\tGet-Process }}",
            ))
        for command in commands:
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assertEqual(self.errors_for("Get-Content -LiteralPath fixture/input.txt"), [])
                    self.assert_process_inspection(form)

    def test_keyword_prefixed_executable_string_consumers_raw_and_serialized(self) -> None:
        self.assertEqual(self.errors_for("Write-Output 'Get-Process'"), [])
        self.assert_process_inspection("Get-Process")
        for keyword in ("return", "throw", "exit", "ReTuRn", "ThRoW", "ExIt"):
            for consumer in (
                "Invoke-Expression 'Get-Process'",
                "iex -Command 'Get-Process'",
                "Microsoft.PowerShell.Utility\\Invoke-Expression 'Get-Process'",
                "& 'Invoke-Expression' 'Get-Process'",
                ". 'iex' 'Get-Process'",
                "& ('Invoke-Expression') 'Get-Process'",
                "& 'Microsoft.PowerShell.Utility\\Invoke-Expression' 'Get-Process'",
                "'Get-Process' | Invoke-Expression",
                "Write-Output 'Get-Process' | iex",
            ):
                for form in self.forms(f"{keyword} {consumer}"):
                    with self.subTest(command=form):
                        self.assertEqual(self.errors_for(f"{keyword} 'Get-Process'"), [])
                        self.assert_process_inspection(form)

    def test_cr_and_crlf_statement_separators_raw_and_serialized(self) -> None:
        self.assertEqual(self.errors_for("Write-Output 'Get-Process'"), [])
        self.assert_process_inspection("Get-Process")
        for separator in ("\r", "\r\n", "\n"):
            for invocation in (
                "Get-Process",
                "Microsoft.PowerShell.Management\\Get-Process",
                "& 'Get-Process'",
                "& ('Get-Process')",
                ". 'Get-Process'",
                "Invoke-Expression 'Get-Process'",
                "& 'Invoke-Expression' 'Get-Process'",
                "Microsoft.PowerShell.Utility\\Invoke-Expression 'Get-Process'",
                "return Get-Process",
                "throw Invoke-Expression 'Get-Process'",
                "exit & 'Get-Process'",
            ):
                for prefix in ("Write-Output ok", "Write-Output 'Get-Process'"):
                    for form in self.forms(prefix + separator + invocation):
                        with self.subTest(command=form):
                            self.assertEqual(self.errors_for(prefix), [])
                            self.assert_process_inspection(form)

    def test_keyword_and_separator_inert_controls_raw_and_serialized(self) -> None:
        commands = [
            "returning Get-Process",
            "throwing Get-Process",
            "exit-code Get-Process",
            "Write-Output 'return Get-Process; throw Invoke-Expression Get-Process'",
            'Write-Output "exit Get-Process"',
        ]
        for keyword in ("return", "throw", "exit", "ReTuRn", "ThRoW", "ExIt"):
            commands.extend((
                f"{keyword} 'Get-Process'",
                f'{keyword} "Get-Process"',
                f"{keyword} Write-Output 'Get-Process'",
                f"{keyword} Get-ProcessNotes",
                f"Write-Output {keyword} Get-Process",
                f"Write-Output {keyword} Invoke-Expression 'Get-Process'",
                f"{keyword} 'Invoke-Expression'; Write-Output 'Get-Process'",
                f"{keyword} Get-Content -LiteralPath fixture/validator.ps1 | "
                "Where-Object { $_ -match 'return Get-Process|throw Invoke-Expression|exit Get-Process' }",
            ))
        for separator in ("\r", "\r\n", "\n"):
            commands.extend((
                f"Write-Output ok{separator}Write-Output 'Get-Process'",
                f"Write-Output ok{separator}Write-Output return Get-Process",
                f"Write-Output 'ok{separator}Get-Process'",
                f'Write-Output "ok{separator}Get-Process"',
                f"$label = 'return Get-Process{separator}throw Get-Process'; Write-Output $label",
                "Get-Content -LiteralPath fixture/validator.ps1 | Where-Object { "
                f"$_ -match 'return Get-Process{separator}throw Get-Process' }}",
            ))
        for command in commands:
            for form in self.forms(command):
                with self.subTest(inert=form):
                    self.assertEqual(self.errors_for(form), [])

    def test_seven_previously_allowed_controls_remain_allowed(self) -> None:
        # These exact controls were independently characterized by PROCESS-GUARD-01.
        commands = (
            "Get-Content -LiteralPath fixture/input.txt",
            "Write-Output 'Get-Process'",
            "$label = 'Get-Process'; Write-Output $label",
            "'Get-Process'",
            "Get-Content -LiteralPath fixture/validator.ps1 | Where-Object { $_ -match 'Get-Process' }",
            "Get-Content -LiteralPath 'fixture/Get-Process-notes.txt'",
            "Get-ProcessNotes",
        )
        for command in commands:
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assertEqual(self.errors_for(form), [])

    def test_quote_boundaries_do_not_hide_adjacent_invocations(self) -> None:
        # Single quotes escape doubled quotes only: neither slash nor backtick
        # can swallow the closing quote and a following executable statement.
        literals = (
            "Write-Output 'prefix; Get-Process'",
            "Write-Output 'prefix''; Get-Process'",
            "Write-Output 'prefix\\'",
            "Write-Output 'prefix`'",
            'Write-Output "Get-Process"',
            "Write-Output '$(Get-Process)'",
            "Write-Output 'Invoke-Expression Get-Process'",
            "Write-Output '& Get-Process'",
        )
        for literal in literals:
            for form in self.forms(literal):
                with self.subTest(inert=form):
                    self.assertEqual(self.errors_for(form), [])
            for chain in (f"{literal}; Get-Process", f"Get-Process; {literal}"):
                for form in self.forms(chain):
                    with self.subTest(executable=form):
                        self.assert_process_inspection(form)

    def test_unsupported_syntax_has_no_inert_data_exemption(self) -> None:
        # Conservative refusals, not a claim that malformed/inert source executes.
        commands = (
            "Write-Output 'Get-Process",
            'Write-Output "Get-Process',
            "Write-Output 'escaped`'; Get-Process",
            'Write-Output "escaped`"; Get-Process"',
            "Write-Output 'Get-Process' # unsupported comment",
            "<# ' #> Get-Process",
            "Write-Output @'\nGet-Process\n'@",
            'Write-Output @"\n$(Get-Process)\n"@',
            "Write-Output \u2018Get-Process\u2019",
            "Write-Output \u201cGet-Process\u201d",
            "Write-Output 'Get-Process\u2019; Get-Process",
            "Write-Output --% Get-Process",
            "$script = 'Get-Process'; Invoke-Expression $script",
            "$script = 'Get-Process'; & $script",
            "$script = 'Get-Process'; ([scriptblock]::Create($script)).Invoke()",
            'Write-Output "$(Write-Output ok; Get-Process)"',
            'Write-Output "$(Write-Output \'quoted\'; Get-Process)"',
            'pwsh -Command "Get-Process',
            "pwsh -Command 'Get-Process' extra",
            'pwsh -Command \'Get-Process\'"$EXTRA"',
            '"$BIN/pwsh.exe" -Command \'Get-Process\'',
            'pwsh -EncodedCommand "Get-Process"',
            "bash -lc 'pwsh -Command Get-Process'",
            "Write-Output 'Get-Process'; pwsh -NoProfile -Command 'Get-Process'",
            "& 'C:/runtime/pwsh.exe' -NoProfile -Command 'Get-Process'",
        )
        for command in commands:
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assert_process_inspection(form)

    def test_nested_expandable_quotes_cannot_hide_execution(self) -> None:
        commands = (
            'Write-Output "$(Write-Output "quoted"; Get-Process)"',
            '$script = \'Get-Process\'; Write-Output "$(& $script)"',
            'Write-Output "$(Invoke-Expression \'Get-Process\')"',
        )
        for command in commands:
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assert_process_inspection(form)

    def test_quoted_and_module_qualified_consumers_are_executable(self) -> None:
        for command in (
            "& 'Invoke-Expression' 'Get-Process'",
            ". 'iex' 'Get-Process'",
            "& ('Invoke-Expression') 'Get-Process'",
            "Microsoft.PowerShell.Utility\\Invoke-Expression 'Get-Process'",
            "& 'Microsoft.PowerShell.Utility\\Invoke-Expression' 'Get-Process'",
            '\"C:/runtime/pwsh.exe\" -NoProfile -Command \'Get-Process\'',
        ):
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assert_process_inspection(form)

    def test_unexecuted_consumer_names_are_not_invocations(self) -> None:
        for command in (
            "Write-Output Invoke-Expression 'Get-Process'",
            "$label = 'Get-Process'; Write-Output pwsh",
            "Get-Content -LiteralPath 'fixture/Get-Process-notes.txt'; Write-Output cmd",
            "'pwsh'; Write-Output 'Get-Process'",
            "'Invoke-Expression'; Write-Output 'Get-Process'",
            "Write-Output 'Get-Process'; 'pwsh'",
        ):
            for form in self.forms(command):
                with self.subTest(command=form):
                    self.assertEqual(self.errors_for(form), [])

    def test_constant_envelopes_scan_payload_and_adjacent_commands(self) -> None:
        inert = "Write-Output 'Get-Process'"
        for executable in ("pwsh", "powershell.exe", '"C:/runtime/pwsh.exe"'):
            for flag in ("-Command", "-c"):
                allowed = f"{executable} {flag} {shlex.quote(inert)}"
                with self.subTest(inert=allowed):
                    self.assertEqual(self.errors_for(allowed), [])
                # Inner payload and outer-shell neighbors are independently
                # executable. No whole-command or launcher exemption is allowed.
                for command in (
                    f"{executable} {flag} {shlex.quote(inert + '; Get-Process')}",
                    f"{executable} {flag} {shlex.quote('Get-Process; ' + inert)}",
                    f"{allowed}; Get-Process",
                    f"Get-Process; {allowed}",
                ):
                    with self.subTest(command=command):
                        self.assert_process_inspection(command)

    def test_inert_process_text_preserves_independent_boundary_guards(self) -> None:
        inert = "Write-Output 'Get-Process'"
        cases = (
            ("git status", "Git command"),
            ("Get-Content .git/HEAD", "Git metadata path"),
            ("Get-Content ../secret.txt", "parent path traversal"),
            (str(REPO_ROOT / "fixture" / "secret.txt"), "candidate repository path"),
            ("Remove-Item Env:GIT_CEILING_DIRECTORIES", "Git isolation override"),
            ("(Get-Location).Parent.GetFiles()", "computed parent path"),
            ("Get-ChildItem Env:", "environment enumeration"),
            ("[System.Environment]::GetEnvironmentVariables()", "environment enumeration"),
            ("Get-Command ruby", "host capability discovery"),
            ("Get-CimInstance Win32_Process", "process inspection"),
            ("Get-WmiObject -Class Win32_Process", "process inspection"),
            ("wmic process get CommandLine", "process inspection"),
            ("cat /proc/self/environ", "process inspection"),
            ("Get-Process | Select-Object Path", "process inspection"),
        )
        for unsafe, violation in cases:
            for chain in (f"{inert}; {unsafe}", f"{unsafe}; {inert}"):
                for form in self.forms(chain):
                    with self.subTest(command=form, violation=violation):
                        self.assertTrue(any(violation in error for error in self.errors_for(form)))

    def test_inert_process_text_does_not_hide_provider_or_tool_events(self) -> None:
        provider = json.dumps({
            "PSPath": "Microsoft.PowerShell.Core\\FileSystem::C:\\workspace\\artifact.txt",
            "PSParentPath": "Microsoft.PowerShell.Core\\FileSystem::C:\\workspace",
            "PSDrive": {"Name": "C"},
            "PSProvider": {"Name": "FileSystem"},
        })
        for form in self.forms("Write-Output 'Get-Process'"):
            with self.subTest(provider=form):
                self.assertEqual(self.errors_for(form), [])
                self.assertTrue(any(
                    "PowerShell provider metadata disclosure" in error
                    for error in self.errors_for(form, output=provider)
                ))
            for item, violation in (
                ({"type": "collab_tool_call", "tool": "spawn_agent"}, "forbidden collaboration events"),
                ({"type": "mcp_tool_call", "tool": "browser", "server": "web"}, "forbidden external, MCP, network, or browser"),
            ):
                with self.subTest(command=form, item=item):
                    self.assertTrue(any(
                        violation in error for error in self.errors_for(form, extra_items=(item,))
                    ))

    def test_two_preexisting_property_word_false_positives_are_retained(self) -> None:
        # Characterization ONLY: these are still conservatively refused, not
        # claimed as correctly classified invocation or accepted inert controls.
        for command in (
            "Write-Output 'Get-Process Path'",
            "Get-Content -LiteralPath fixture/validator.ps1 | Where-Object { $_ -match 'Get-Process|Path' }",
        ):
            for form in self.forms(command):
                with self.subTest(known_false_positive=form):
                    self.assert_process_inspection(form)

    def test_host_boundary_receipt_uses_v13_and_retains_skill_guard_v5(self) -> None:
        self.assertEqual(TASK_OUTPUT_SAFETY_GUARD, "task-output-and-host-boundary-safety-v13")
        self.assertEqual(TASK_SKILL_BODY_READ_GUARD, "named-skill-path-command-events-v5")
        receipt = canonical_task_isolation_receipt()
        self.assertEqual(receipt["task_output_safety_guard"], TASK_OUTPUT_SAFETY_GUARD)
        self.assertEqual(receipt["skill_body_read_guard"], TASK_SKILL_BODY_READ_GUARD)


if __name__ == "__main__":
    unittest.main()
