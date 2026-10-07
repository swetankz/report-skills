#!/usr/bin/env python3
"""Capture a private model-free profile anchor; this is never human approval."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from evaluation_common import (
    EvaluationError,
    REASONING_EFFORTS,
    _private_profile_path,
    codex_execution_profile,
    execution_profile_anchor_document,
    file_sha256,
    find_codex_command,
    repository_receipt,
    require_unchanged_repository,
    write_private_profile_json_exclusive,
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New private anchor file inside ignored .build")
    parser.add_argument("--codex-command", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True, choices=REASONING_EFFORTS)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        target = _private_profile_path(args.output)
        if target.exists() or target.is_symlink():
            raise EvaluationError("Refusing to overwrite an existing profile anchor")
        repository = repository_receipt(require_clean=True)
        profile = codex_execution_profile(find_codex_command(args.codex_command), args.model, args.reasoning_effort)
        require_unchanged_repository(repository)
        value = execution_profile_anchor_document(profile, repository)
        write_private_profile_json_exclusive(target, value)
        print(json.dumps({"profile_anchor": str(target), "profile_anchor_sha256": file_sha256(target),
                          "model_calls": 0, "qualification_or_publication_authority": False}, indent=2))
        return 0
    except (EvaluationError, OSError, subprocess.SubprocessError) as error:
        print(f"Profile capture refused: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
