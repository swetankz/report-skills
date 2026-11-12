from __future__ import annotations

import json
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_behavioral_benchmark as benchmark


INVENTORY = (
    r"Get-ChildItem -LiteralPath '.\fixture' -Recurse -File | "
    r"Where-Object { $_.Name -ne 'SKILL.md' -and $_.Name -ne 'AGENTS.md' } | "
    r"ForEach-Object { [string]$_.FullName.Replace([System.IO.Path]::GetFullPath('.\'), '') }"
)
# Exact item_2 serialization from the failed observation, with only the private
# executable directory replaced by a synthetic directory. No private run needed.
SERIALIZED_INVENTORY = json.loads(r'''{"command":"\"C:\\\\runtime\\\\pwsh.exe\" -Command \"Get-ChildItem -LiteralPath '.\\\\fixture' -Recurse -File | Where-Object { \"'$_.Name -ne '\"'SKILL.md' -and \"'$_.Name -ne '\"'AGENTS.md' } | ForEach-Object { [string]\"'$_.FullName.Replace([System.IO.Path]::GetFullPath('\"'.\\\\'), '') }\""}''')['command']


def transcript(command: str, item_id: str = 'cmd-1') -> str:
    return json.dumps({'type': 'item.completed', 'item': {
        'id': item_id, 'type': 'command_execution', 'command': command,
        'exit_code': 0, 'aggregated_output': 'fixture/brief.yaml\n',
    }})


class SkillFilenameInventoryTests(unittest.TestCase):
    def test_metadata_only_inventory_and_recorded_serialization_are_allowed(self):
        commands = (
            INVENTORY,
            INVENTORY.replace('\\', '/'),
            INVENTORY.upper(),
            '\n  ' + INVENTORY.replace(' | ', '\n | ') + '\n',
            SERIALIZED_INVENTORY,
            'pwsh -Command ' + shlex.quote(INVENTORY),
            '"C:/runtime/powershell.exe" -Command ' + shlex.quote(INVENTORY),
        )
        for command in commands:
            for configuration in ('with_skill', 'without_skill'):
                with self.subTest(command=command, configuration=configuration):
                    self.assertTrue(benchmark.is_fixture_filename_inventory(command))
                    self.assertEqual(benchmark.skill_body_read_violations(
                        transcript(command), {'configuration': configuration, 'skill': 'report-skills'}
                    ), [])

    def test_near_misses_and_body_access_remain_rejected(self):
        unsafe = {
            'disjunction': INVENTORY.replace("-and $_.Name -ne 'AGENTS.md'", '-or $true'),
            'negated filter': INVENTORY.replace("$_.Name -ne 'SKILL.md'", "-not ($_.Name -ne 'SKILL.md')"),
            'positive filter': INVENTORY.replace("-ne 'SKILL.md'", "-eq 'SKILL.md'"),
            'case-sensitive filter': INVENTORY.replace("-ne 'SKILL.md'", "-cne 'SKILL.md'"),
            'different file': INVENTORY.replace("'AGENTS.md'", "'SKILL.md'"),
            'missing filter': INVENTORY.replace(" -and $_.Name -ne 'AGENTS.md'", ''),
            'variable root': INVENTORY.replace("'.\\fixture'", '$root'),
            'outside root': INVENTORY.replace("'.\\fixture'", "'Q:/outside'"),
            'parent root': INVENTORY.replace("'.\\fixture'", "'../fixture'"),
            'candidate root': INVENTORY.replace("'.\\fixture'", "'.benchmark_skill/other'"),
            'global root': INVENTORY.replace("'.\\fixture'", "'Q:/.codex/skills/other'"),
            'subexpression root': INVENTORY.replace("'.\\fixture'", "$(Get-Content 'SKILL.md')"),
            'alias': INVENTORY.replace('Get-ChildItem', 'gci'),
            'reader pipeline': INVENTORY + ' | Get-Content',
            'reader block': INVENTORY.replace(
                "[string]$_.FullName.Replace([System.IO.Path]::GetFullPath('.\\'), '')",
                '[System.IO.File]::ReadAllText($_.FullName)'),
            'direct global read': INVENTORY + "; Get-Content 'Q:/.codex/skills/other/SKILL.md'",
            'direct file API': INVENTORY + "; [System.IO.File]::ReadAllText('Q:/outside/SKILL.md')",
            'prefix': 'Write-Output safe; ' + INVENTORY,
            'suffix': INVENTORY + '; Write-Output done',
            'newline read': INVENTORY + "\nGet-Content 'SKILL.md'",
            'redirection': INVENTORY + ' > artifacts/list.txt',
            'comment': INVENTORY + ' # extra',
            'nested invocation': '& { ' + INVENTORY + ' }',
            'trailing escape': INVENTORY + '`',
            'malformed': INVENTORY[:-1],
            'extra wrapper argument': 'pwsh -Command ' + shlex.quote(INVENTORY) + ' extra',
            'wrapper chain': 'pwsh -Command ' + shlex.quote(INVENTORY) + '; Get-Content SKILL.md',
            'alternate wrapper': 'bash -c ' + shlex.quote(INVENTORY),
            'expanding wrapper': 'pwsh -Command "' + INVENTORY + '"',
            'expanding executable': '"$BIN/pwsh.exe" -Command ' + shlex.quote(INVENTORY),
            'extra wrapper switch': 'pwsh -NoProfile -Command ' + shlex.quote(INVENTORY),
            'dynamic invocation': 'Invoke-Expression ' + shlex.quote(INVENTORY),
            'serialized chain': SERIALIZED_INVENTORY + '; Get-Content SKILL.md',
        }
        for label, command in unsafe.items():
            for configuration in ('with_skill', 'without_skill'):
                with self.subTest(label=label, configuration=configuration):
                    self.assertFalse(benchmark.is_fixture_filename_inventory(command))
                    self.assertTrue(benchmark.skill_body_read_violations(
                        transcript(command), {'configuration': configuration, 'skill': 'report-skills'}
                    ))

    def test_safe_event_does_not_hide_another_events_skill_read(self):
        for command in (
            'Get-Content Q:/.codex/skills/other/SKILL.md',
            "[System.IO.File]::ReadAllText('Q:/outside/SKILL.md')",
            'Get-Content .benchmark_skill/other/SKILL.md',
        ):
            events = transcript(SERIALIZED_INVENTORY) + '\n' + transcript(command, 'cmd-2')
            self.assertEqual(benchmark.skill_body_read_violations(events, {
                'configuration': 'without_skill', 'skill': 'report-skills',
            }), ['non-candidate named SKILL.md reference detected in command event cmd-2'])

    def test_existing_candidate_and_baseline_boundaries_remain(self):
        run = {'configuration': 'with_skill', 'skill': 'report-skills'}
        candidate = transcript('Get-Content .benchmark_skill/report-skills/SKILL.md')
        self.assertEqual(benchmark.skill_body_read_violations(candidate, run), [])
        self.assertTrue(benchmark.skill_body_read_violations(candidate, {
            **run, 'configuration': 'without_skill',
        }))
        self.assertTrue(benchmark.skill_body_read_violations(transcript(
            'Get-Content .benchmark_skill/report-skills/SKILL.md, Q:/outside/skills/other/SKILL.md'
        ), run))


if __name__ == '__main__':
    unittest.main()
