from __future__ import annotations

import json
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_behavioral_benchmark as benchmark


CANDIDATE = "Get-Content '.benchmark_skill/sample/SKILL.md'"
CLASSIFIER = "if($path -like '.benchmark_skill/*'){'candidate'}else{'fixture'}"
RUN = {'configuration': 'with_skill', 'skill': 'sample'}
ERROR = 'non-candidate named SKILL.md reference detected in command event cmd-1'


def transcript(command: str, event_id: str = 'cmd-1') -> str:
    return json.dumps({'type': 'item.completed', 'item': {
        'id': event_id, 'type': 'command_execution', 'command': command,
    }})


class SkillLiteralComparisonTests(unittest.TestCase):
    def test_candidate_read_positive_control(self):
        self.assertEqual(benchmark.skill_body_read_violations(transcript(CANDIDATE), RUN), [])

    def test_literal_provenance_classifier_is_not_another_skill_read(self):
        for classifier in ('$role=' + CLASSIFIER, '$role=$(' + CLASSIFIER + ')'):
            with self.subTest(classifier=classifier):
                self.assertEqual(benchmark.skill_body_read_violations(
                    transcript(CANDIDATE + '; ' + classifier), RUN,
                ), [])

    def test_reviewed_classifier_syntax_variants_are_allowed(self):
        row = (
            "$row=[pscustomobject]@{path=$path; role=$("
            "if($path -like '.benchmark_skill/*'){'activated workspace skill'}"
            "elseif($path -like 'fixture/*'){'synthetic fixture'}else{'generated artifact'})}"
        )
        commands = (
            CANDIDATE + '; ' + row,
            CANDIDATE + '; $role=' + CLASSIFIER.upper(),
            CANDIDATE + ';\n$role=\n' + CLASSIFIER.replace('if(', 'if ( '),
            CANDIDATE + '; $text="line`n"; $role=' + CLASSIFIER,
            CANDIDATE + "; $text='doubled''quote'; $role=" + CLASSIFIER,
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(command), RUN), [])

    def test_constant_native_powershell_quote_envelopes_are_supported(self):
        payload = CANDIDATE + '; $role=$(' + CLASSIFIER + ')'
        for executable in ('pwsh', 'powershell.exe', '"C:/runtime/pwsh.exe"'):
            command = executable + ' -Command ' + shlex.quote(payload)
            with self.subTest(executable=executable):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(command), RUN), [])

    def test_native_envelope_preserves_baseline_and_other_skill_boundaries(self):
        payload = CANDIDATE + '; $role=$(' + CLASSIFIER + ')'
        wrapped = 'pwsh -Command ' + shlex.quote(payload)
        self.assertEqual(benchmark.skill_body_read_violations(
            transcript(wrapped), {**RUN, 'configuration': 'without_skill'},
        ), [ERROR])
        for suffix in (
            "; Get-Content '.benchmark_skill/other/SKILL.md'",
            "; Get-Content '.benchmark_skill/*'",
            "; Get-Content -like '.benchmark_skill/*'",
        ):
            for command in ('pwsh -Command ' + shlex.quote(payload + suffix), wrapped + suffix):
                with self.subTest(command=command):
                    self.assertEqual(benchmark.skill_body_read_violations(transcript(command), RUN), [ERROR])
        for executable in ('"Q:/.codex/skills/runtime/pwsh.exe"',
                           '".benchmark_skill/other/powershell.exe"'):
            with self.subTest(executable=executable):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(
                    executable + ' -Command ' + shlex.quote(payload),
                ), RUN), [ERROR])

    def test_unknown_or_expanding_native_envelopes_fail_closed(self):
        payload = CANDIDATE + '; $role=$(' + CLASSIFIER + ')'
        wrapped = 'pwsh -Command ' + shlex.quote(payload)
        commands = (
            wrapped + ' extra',
            wrapped + '; Write-Output done',
            'pwsh -NoProfile -Command ' + shlex.quote(payload),
            'pwsh -c ' + shlex.quote(payload),
            'bash -c ' + shlex.quote(payload),
            '"$BIN/pwsh.exe" -Command ' + shlex.quote(payload),
            'pwsh -Command "' + payload + '"',
            'pwsh -EncodedCommand YQ==; ' + payload,
            'pwsh -Command ' + shlex.quote(wrapped),
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(command), RUN), [ERROR])

    def test_native_envelope_cannot_activate_quoted_or_comment_text(self):
        for source in (
            'Write-Output "$role=' + CLASSIFIER + '"',
            'Write-Output \'$role=' + CLASSIFIER.replace("'", "''") + "'",
            '# $role=' + CLASSIFIER,
            "$text=@'\n$role=" + CLASSIFIER + "\n'@",
            'Write-Output --% $role=$(' + CLASSIFIER + ')',
        ):
            with self.subTest(source=source):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(
                    'pwsh -Command ' + shlex.quote(CANDIDATE + '; ' + source),
                ), RUN), [ERROR])

    def test_baseline_never_gains_candidate_access(self):
        for command in (CANDIDATE, CANDIDATE + '; $role=' + CLASSIFIER):
            with self.subTest(command=command):
                self.assertEqual(benchmark.skill_body_read_violations(
                    transcript(command), {**RUN, 'configuration': 'without_skill'},
                ), [ERROR])

    def test_classifier_does_not_hide_direct_or_chained_other_skill_reads(self):
        readers = (
            "Get-Content '.benchmark_skill/other/SKILL.md'",
            "Get-Content '.benchmark_skill/sample-evil/SKILL.md'",
            "Get-Content 'Q:/.codex/skills/other/SKILL.md'",
            "Get-Content 'Q:/.agents/skills/other/SKILL.md'",
            "Get-Content 'Q:/.codex/plugins/package/SKILL.md'",
            "[System.IO.File]::ReadAllText('Q:/skills/other/SKILL.md')",
        )
        for reader in readers:
            for commands in ((reader,), (CANDIDATE, '$role=' + CLASSIFIER, reader),
                             (reader, '$role=' + CLASSIFIER, CANDIDATE)):
                with self.subTest(reader=reader, commands=commands):
                    self.assertEqual(benchmark.skill_body_read_violations(
                        transcript('; '.join(commands)), RUN,
                    ), [ERROR])

    def test_wildcard_io_operand_is_not_exempted(self):
        for reader in (
            "Get-Content '.benchmark_skill/*'",
            "Get-Content -Path '.benchmark_skill/*/SKILL.md'",
            "Get-ChildItem '.benchmark_skill/*' | Get-Content",
            "[System.IO.File]::ReadAllText('.benchmark_skill/*')",
        ):
            with self.subTest(reader=reader):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(
                    CANDIDATE + '; $role=' + CLASSIFIER + '; ' + reader,
                ), RUN), [ERROR])

    def test_like_command_parameter_is_not_a_comparison(self):
        for command in (
            "Get-Content -like '.benchmark_skill/*'",
            "Test-Path -like '.benchmark_skill/*'",
            "$role=Get-Content -like '.benchmark_skill/*'",
            "$role=if(Get-Content -like '.benchmark_skill/*'){'candidate'}else{'fixture'}",
        ):
            with self.subTest(command=command):
                self.assertEqual(benchmark.skill_body_read_violations(
                    transcript(CANDIDATE + '; ' + command), RUN,
                ), [ERROR])

    def test_quoted_code_is_not_a_comparison(self):
        for quoted in ('"$role=' + CLASSIFIER + '"',
                       "'$role=" + CLASSIFIER.replace("'", "''") + "'"):
            for suffix in ('', '; $role=' + CLASSIFIER):
                with self.subTest(quoted=quoted, suffix=suffix):
                    self.assertEqual(benchmark.skill_body_read_violations(
                        transcript(CANDIDATE + '; Write-Output ' + quoted + suffix), RUN,
                    ), [ERROR])

    def test_comment_and_here_string_lookalikes_fail_closed(self):
        lookalikes = (
            '# $role=' + CLASSIFIER,
            '<# $role=' + CLASSIFIER + ' #>',
            "$text=@'\n$role=" + CLASSIFIER + "\n'@",
            '$text=@"\n$role=' + CLASSIFIER + '\n"@',
        )
        for lookalike in lookalikes:
            for prefix in ('', '$role=' + CLASSIFIER + '; '):
                with self.subTest(lookalike=lookalike, prefix=prefix):
                    self.assertEqual(benchmark.skill_body_read_violations(
                        transcript(CANDIDATE + '; ' + prefix + lookalike), RUN,
                    ), [ERROR])

    def test_interpolated_or_computed_operands_stay_fail_closed(self):
        conditions = (
            '$path -like ".benchmark_skill/*"',
            '$path -like "$root/.benchmark_skill/*"',
            '$path -like "$(Get-Content \'.benchmark_skill/*\')"',
            "$path -like ('.benchmark_skill/*')",
            "$path -like '.benchmark_skill/*' + $suffix",
            "$path.Name -like '.benchmark_skill/*'",
            "${path} -like '.benchmark_skill/*'",
            "$path -match '.benchmark_skill/*'",
            "$path -clike '.benchmark_skill/*'",
            "$path -like '.benchmark_skill/*' -or $true",
            "$path -like '.benchmark_skill/*'.ToString()",
        )
        for condition in conditions:
            with self.subTest(condition=condition):
                command = CANDIDATE + "; $role=if(" + condition + "){'candidate'}else{'fixture'}"
                self.assertEqual(benchmark.skill_body_read_violations(transcript(command), RUN), [ERROR])

    def test_dynamic_and_nested_execution_contexts_stay_fail_closed(self):
        for command in (
            "Invoke-Expression '$role=" + CLASSIFIER.replace("'", "''") + "'",
            'Invoke-Expression ($role=' + CLASSIFIER + ')',
            'iex ($role=' + CLASSIFIER + ')',
            'Invoke-Command { $role=' + CLASSIFIER + ' }',
            '& { $role=' + CLASSIFIER + ' }',
            '. { $role=' + CLASSIFIER + ' }',
            '& $executor; $role=' + CLASSIFIER,
            '[scriptblock]::Create($code); $role=' + CLASSIFIER,
            '$executor.Invoke(); $role=' + CLASSIFIER,
            'pwsh -Command $code; $role=' + CLASSIFIER,
            'powershell -EncodedCommand YQ==; $role=' + CLASSIFIER,
            '$text="$(Get-Content fixture/data.txt)"; $role=' + CLASSIFIER,
            '$role=`\n' + CLASSIFIER,
        ):
            with self.subTest(command=command):
                self.assertEqual(benchmark.skill_body_read_violations(
                    transcript(CANDIDATE + '; ' + command), RUN,
                ), [ERROR])

    def test_malformed_or_nonlabel_branch_stays_fail_closed(self):
        for classifier in (
            '$role=$(' + CLASSIFIER,
            '$role=' + CLASSIFIER + ')',
            '$role=' + CLASSIFIER.replace("{'candidate'}", '{Get-Content $path}'),
            '$role=' + CLASSIFIER.replace("{'candidate'}", '{"candidate"}'),
            '$role=' + CLASSIFIER.replace("'candidate'", "'candidate/label'"),
            '$role=' + CLASSIFIER.replace("'candidate'", "'candidate''label'"),
        ):
            with self.subTest(classifier=classifier):
                self.assertEqual(benchmark.skill_body_read_violations(
                    transcript(CANDIDATE + '; ' + classifier), RUN,
                ), [ERROR])

    def test_unsupported_lexical_contexts_cannot_mimic_executable_classifiers(self):
        lookalikes = (
            'Write-Output --% $role=$(' + CLASSIFIER + ')',
            'Write-Output \u201c\n$role=' + CLASSIFIER + '\n\u201d',
            'Write-Output "prefix\u201d"\n$role=' + CLASSIFIER + '\n"\u201c"',
            "cat <<'END'\n$role=" + CLASSIFIER + '\nEND',
        )
        for lookalike in lookalikes:
            with self.subTest(lookalike=lookalike):
                self.assertEqual(benchmark.skill_body_read_violations(
                    transcript(CANDIDATE + '; ' + lookalike), RUN,
                ), [ERROR])

    def test_only_exact_wildcard_operand_is_removed(self):
        suffixes = (
            "; Write-Output '.benchmark_skill/*'",
            "; $role=if($path -like '.benchmark_skill/other/SKILL.md'){'other'}else{'fixture'}",
            "; $role=if($path -like 'Q:/skills/*'){'other'}else{'fixture'}",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                self.assertEqual(benchmark.skill_body_read_violations(transcript(
                    CANDIDATE + '; $role=' + CLASSIFIER + suffix,
                ), RUN), [ERROR])
        self.assertEqual(benchmark.skill_body_read_violations(transcript(
            '$role=' + CLASSIFIER + "; Get-Content 'Q:/outside/SKILL.md'",
        ), RUN), [ERROR])

    def test_safe_event_does_not_hide_another_events_read(self):
        events = transcript(CANDIDATE + '; $role=' + CLASSIFIER)
        events += '\n' + transcript("Get-Content '.benchmark_skill/other/SKILL.md'", 'cmd-2')
        self.assertEqual(benchmark.skill_body_read_violations(events, RUN), [ERROR.replace('cmd-1', 'cmd-2')])


if __name__ == '__main__':
    unittest.main()
