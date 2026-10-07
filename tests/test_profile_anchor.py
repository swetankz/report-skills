from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import evaluation_common  # noqa: E402
import capture_evaluation_profile  # noqa: E402
import grade_behavioral_benchmark  # noqa: E402
import run_behavioral_benchmark  # noqa: E402
import run_blind_comparisons  # noqa: E402
import run_gate1_evidence  # noqa: E402
import run_trigger_evals  # noqa: E402


PROFILE_IDENTITY_KEYS = (
    "model",
    "reasoning_effort",
    "service_tier",
    "codex_invocation",
    "codex_timeout_enforcement",
    "codex_cli_version",
    "codex_command_sha256",
    "codex_implementation_sha256",
    "codex_managed_environment_sha256",
    "selected_model_sha256",
    "model_isolation_prompt_probe",
    "model_isolation_prompt_schema",
    "model_isolation_prompt_probe_sha256",
    "python_version",
    "platform",
)


def selected_metadata() -> dict:
    return {
        "slug": "gpt-6.1-sol",
        "display_name": "Synthetic Sol \u2014 \u092a\u0930\u0940\u0915\u094d\u0937\u0923",
        "default_reasoning_level": "low",
        "supported_reasoning_levels": [{"effort": "ultra"}],
        "additional_speed_tiers": ["fast"],
    }


def selected_digest(metadata: dict) -> str:
    # Pin the existing native profile algorithm, including ASCII escaping.
    serialized = json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def synthetic_profile() -> dict:
    metadata = selected_metadata()
    return {
        "model": "gpt-6.1-sol",
        "reasoning_effort": "ultra",
        "service_tier": "fast",
        "codex_invocation": evaluation_common.CODEX_INVOCATION_MODE,
        "codex_timeout_enforcement": evaluation_common.CODEX_TIMEOUT_ENFORCEMENT_MODE,
        "codex_cli_version": "codex-cli synthetic-offline",
        "codex_command": "synthetic-native-not-launched",
        "codex_command_sha256": "a" * 64,
        "codex_implementation": "synthetic-native-not-launched",
        "codex_implementation_sha256": "b" * 64,
        "codex_managed_package_root": None,
        "codex_managed_by": None,
        "codex_managed_environment_sha256": "c" * 64,
        "model_catalog_sha256": "d" * 64,
        "selected_model_sha256": selected_digest(metadata),
        "selected_model_metadata": metadata,
        "model_default_reasoning_effort": "low",
        "model_supported_reasoning_efforts": ["ultra"],
        "model_isolation_prompt_probe": evaluation_common.MODEL_PROMPT_ISOLATION_PROBE_METHOD,
        "model_isolation_prompt_schema": evaluation_common.MODEL_PROMPT_ISOLATION_PROBE_SCHEMA,
        "model_isolation_prompt_probe_sha256": "e" * 64,
        "python_version": "3.12.13",
        "platform": "Synthetic-Offline-Platform",
    }


class ProfileAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()
        self.private = self.root / ".build" / "profile-test"
        self.private.mkdir(parents=True)
        self.profile = synthetic_profile()
        self.repository = {
            "root": str(self.root),
            "commit": "1" * 40,
            "tree": "2" * 40,
            "dirty": False,
        }
        self.root_patch = patch.object(evaluation_common, "REPO_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        # Any unexpected external probe/model invocation is a test failure.
        self.subprocess_patch = patch.object(
            evaluation_common.subprocess,
            "run",
            side_effect=AssertionError("offline tests must not start a subprocess"),
        )
        self.subprocess_mock = self.subprocess_patch.start()
        self.addCleanup(self.subprocess_patch.stop)
        self.repository_patch = patch.object(
            evaluation_common, "repository_receipt", return_value=self.repository
        )
        self.repository_patch.start()
        self.addCleanup(self.repository_patch.stop)

    def document(self) -> dict:
        return {
            "schema_version": "1.0",
            "kind": "evaluation-profile-anchor",
            "evaluation_method_version": evaluation_common.EVALUATION_METHOD_VERSION,
            "execution_profile": copy.deepcopy(self.profile),
            "repository": copy.deepcopy(self.repository),
            "qualification_or_publication_authority": False,
        }

    def write_anchor(self, document: dict | None = None, name: str = "anchor.json") -> tuple[Path, str]:
        path = self.private / name
        path.write_text(
            json.dumps(self.document() if document is None else document) + "\n",
            encoding="utf-8",
        )
        return path, evaluation_common.file_sha256(path)

    def load_anchor(self) -> dict:
        path, digest = self.write_anchor()
        return evaluation_common.load_execution_profile_anchor(path, digest)

    def assert_rejected_document(self, document: dict) -> None:
        path, digest = self.write_anchor(document)
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.load_execution_profile_anchor(path, digest)

    def test_identity_contract_keeps_all_fifteen_existing_fields(self) -> None:
        self.assertEqual(evaluation_common.PROFILE_IDENTITY_KEYS, PROFILE_IDENTITY_KEYS)
        self.assertEqual(
            evaluation_common.REPOSITORY_IDENTITY_KEYS, ("commit", "tree", "dirty")
        )

    def test_exact_private_hash_bound_anchor_matches(self) -> None:
        path, digest = self.write_anchor()
        anchor = evaluation_common.load_execution_profile_anchor(path, digest)
        self.assertEqual(anchor["execution_profile"], self.profile)
        self.assertEqual(anchor["repository"], self.repository)
        self.assertEqual(anchor["_anchor_path"], str(path.resolve()))
        self.assertEqual(anchor["_anchor_sha256"], digest)
        evaluation_common.require_execution_profile_anchor(
            anchor, copy.deepcopy(self.profile), copy.deepcopy(self.repository), "trigger"
        )
        self.subprocess_mock.assert_not_called()

    def test_loader_requires_both_anchor_and_valid_expected_hash(self) -> None:
        path, digest = self.write_anchor()
        for candidate, expected_hash in (
            (None, digest),
            (path, None),
            (path, ""),
            (path, "g" * 64),
            (path, "a" * 63),
            (path, "f" * 64),
            (self.private / "missing.json", digest),
        ):
            with self.subTest(candidate=candidate, expected_hash=expected_hash):
                with self.assertRaises(evaluation_common.EvaluationError):
                    evaluation_common.load_execution_profile_anchor(candidate, expected_hash)
        self.subprocess_mock.assert_not_called()

    def test_loader_refuses_public_or_outside_repository_paths(self) -> None:
        path, _ = self.write_anchor()
        for target in (self.root / "public-anchor.json", self.root.parent / (self.root.name + "-anchor.json")):
            with self.subTest(target=target):
                target.write_bytes(path.read_bytes())
                self.addCleanup(target.unlink, missing_ok=True)
                with self.assertRaises(evaluation_common.EvaluationError):
                    evaluation_common.load_execution_profile_anchor(
                        target, evaluation_common.file_sha256(target)
                    )

    def test_loader_refuses_directory_and_symlink_like_entry(self) -> None:
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.load_execution_profile_anchor(self.private, "a" * 64)
        path, digest = self.write_anchor()
        original_lstat = Path.lstat

        def link_lstat(candidate: Path, *args, **kwargs):
            if candidate == path:
                return SimpleNamespace(
                    st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0x400
                )
            return original_lstat(candidate, *args, **kwargs)

        with patch.object(Path, "lstat", link_lstat):
            with self.assertRaises(evaluation_common.EvaluationError):
                evaluation_common.load_execution_profile_anchor(path, digest)

    def test_loader_refuses_reparse_ancestor(self) -> None:
        path, digest = self.write_anchor()
        original_lstat = Path.lstat

        def reparse_lstat(candidate: Path, *args, **kwargs):
            if candidate == self.private:
                return SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400
                )
            return original_lstat(candidate, *args, **kwargs)

        with patch.object(Path, "lstat", reparse_lstat):
            with self.assertRaises(evaluation_common.EvaluationError):
                evaluation_common.load_execution_profile_anchor(path, digest)

    def test_loader_refuses_malformed_json_duplicates_and_nonfinite_values(self) -> None:
        valid = json.dumps(self.document())
        samples = (
            "not json",
            "[]",
            "null",
            valid[:-1],
            valid.replace('"schema_version": "1.0"', '"schema_version": "1.0", "schema_version": "1.0"'),
            valid.replace('"slug": "gpt-6.1-sol"', '"slug": "gpt-6.1-sol", "slug": "gpt-6.1-sol"'),
            valid.replace('"dirty": false', '"dirty": NaN'),
            valid.replace('"dirty": false', '"dirty": Infinity'),
            valid.replace('"dirty": false', '"dirty": -Infinity'),
            valid.replace('"dirty": false', '"dirty": 1e9999'),
        )
        for index, raw in enumerate(samples):
            with self.subTest(index=index):
                path = self.private / "malformed.json"
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(evaluation_common.EvaluationError):
                    evaluation_common.load_execution_profile_anchor(
                        path, evaluation_common.file_sha256(path)
                    )

    def test_loader_refuses_wrong_schema_method_kind_or_authority(self) -> None:
        for key, value in (
            ("schema_version", "2.0"),
            ("kind", "human-approval"),
            ("evaluation_method_version", "report-skills-release-evaluation-v48"),
            ("qualification_or_publication_authority", True),
            ("qualification_or_publication_authority", 0),
        ):
            with self.subTest(key=key, value=value):
                document = self.document()
                document[key] = value
                self.assert_rejected_document(document)
        document = self.document()
        document["unexpected"] = "not part of the anchor contract"
        self.assert_rejected_document(document)

    def test_loader_refuses_missing_empty_or_wrong_type_identity_fields(self) -> None:
        for key in PROFILE_IDENTITY_KEYS:
            for value in (None, "", [], {}):
                with self.subTest(key=key, value=value):
                    document = self.document()
                    document["execution_profile"][key] = value
                    self.assert_rejected_document(document)
            with self.subTest(key=key, value="missing"):
                document = self.document()
                document["execution_profile"].pop(key)
                self.assert_rejected_document(document)

    def test_loader_refuses_dirty_or_invalid_repository(self) -> None:
        for key, value in (
            ("dirty", True),
            ("dirty", 0),
            ("commit", ""),
            ("commit", "not a commit"),
            ("tree", ""),
            ("tree", "not a tree"),
        ):
            with self.subTest(key=key, value=value):
                document = self.document()
                document["repository"][key] = value
                self.assert_rejected_document(document)

    def test_selected_metadata_digest_preserves_existing_unicode_algorithm(self) -> None:
        metadata = selected_metadata()
        expected = selected_digest(metadata)
        self.assertEqual(
            evaluation_common.selected_model_metadata_sha256(metadata), expected
        )
        unescaped = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertNotEqual(expected, hashlib.sha256(unescaped.encode("utf-8")).hexdigest())

    def test_loader_refuses_missing_or_tampered_exact_selected_metadata(self) -> None:
        for value in (None, [], "metadata", {}):
            with self.subTest(value=value):
                document = self.document()
                document["execution_profile"]["selected_model_metadata"] = value
                self.assert_rejected_document(document)
        document = self.document()
        document["execution_profile"].pop("selected_model_metadata")
        self.assert_rejected_document(document)
        for change in ("display_name", "slug", "additional_speed_tiers"):
            with self.subTest(change=change):
                document = self.document()
                document["execution_profile"]["selected_model_metadata"][change] = "changed"
                self.assert_rejected_document(document)

    def test_all_profile_identity_drift_is_rejected(self) -> None:
        anchor = self.load_anchor()
        for key in PROFILE_IDENTITY_KEYS:
            with self.subTest(key=key):
                actual = copy.deepcopy(self.profile)
                actual[key] = "f" * 64 if key.endswith("sha256") else "different"
                with self.assertRaises(evaluation_common.EvaluationError):
                    evaluation_common.require_execution_profile_anchor(
                        anchor, actual, self.repository, "task"
                    )
        self.subprocess_mock.assert_not_called()

    def test_repository_identity_drift_is_rejected(self) -> None:
        anchor = self.load_anchor()
        for key, value in (("commit", "3" * 40), ("tree", "4" * 40), ("dirty", True)):
            with self.subTest(key=key):
                actual = dict(self.repository, **{key: value})
                with self.assertRaises(evaluation_common.EvaluationError):
                    evaluation_common.require_execution_profile_anchor(
                        anchor, self.profile, actual, "grader"
                    )

    def test_cosmetic_selected_metadata_change_is_not_exempted(self) -> None:
        anchor = self.load_anchor()
        actual = copy.deepcopy(self.profile)
        actual["selected_model_metadata"]["display_name"] += " (cosmetic only)"
        actual["selected_model_sha256"] = selected_digest(actual["selected_model_metadata"])
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.require_execution_profile_anchor(
                anchor, actual, self.repository, "comparison"
            )

    def test_retained_metadata_mutation_under_original_digest_is_rejected(self) -> None:
        anchor = self.load_anchor()
        actual = copy.deepcopy(self.profile)
        actual["selected_model_metadata"]["display_name"] = "tampered but original SHA"
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.require_execution_profile_anchor(
                anchor, actual, self.repository, "grader"
            )
        self.assertTrue(
            evaluation_common.model_isolation_profile_validation_errors(actual, "Synthetic receipt")
        )

    def test_unrelated_catalog_hash_does_not_weaken_selected_identity(self) -> None:
        anchor = self.load_anchor()
        actual = dict(self.profile, model_catalog_sha256="f" * 64)
        evaluation_common.require_execution_profile_anchor(
            anchor, actual, self.repository, "trigger"
        )

    def test_original_anchor_tampering_during_discovery_is_rejected(self) -> None:
        path, digest = self.write_anchor()
        anchor = evaluation_common.load_execution_profile_anchor(path, digest)
        tampered = self.document()
        tampered["execution_profile"]["model_catalog_sha256"] = "f" * 64
        path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.require_execution_profile_anchor(
                anchor, self.profile, self.repository, "task"
            )

    def test_exact_actual_metadata_is_preserved_before_identity_failure(self) -> None:
        anchor = self.load_anchor()
        actual = copy.deepcopy(self.profile)
        actual["selected_model_metadata"]["display_name"] = "Actual changed metadata"
        actual["selected_model_sha256"] = selected_digest(actual["selected_model_metadata"])
        evaluation_common.preserve_execution_profile_discovery(
            anchor, actual, self.repository, "trigger"
        )
        directory = self.private / "anchor.json.discoveries"
        paths = list(directory.glob("*.json"))
        self.assertEqual(len(paths), 1)
        preserved = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual(preserved["execution_profile"], actual)
        self.assertEqual(preserved["repository"], self.repository)
        self.assertIn(anchor["_anchor_sha256"], json.dumps(preserved))
        self.assertNotIn("model_catalog", preserved)
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.require_execution_profile_anchor(
                anchor, actual, self.repository, "trigger"
            )
        self.assertEqual(json.loads(paths[0].read_text(encoding="utf-8")), preserved)

    def test_discovery_diagnostics_create_new_records_never_replace_existing(self) -> None:
        anchor = self.load_anchor()
        evaluation_common.preserve_execution_profile_discovery(
            anchor, self.profile, self.repository, "task"
        )
        directory = self.private / "anchor.json.discoveries"
        first = list(directory.glob("*.json"))
        self.assertEqual(len(first), 1)
        initial_bytes = first[0].read_bytes()
        actual = dict(self.profile, model_catalog_sha256="f" * 64)
        evaluation_common.preserve_execution_profile_discovery(
            anchor, actual, self.repository, "task"
        )
        self.assertEqual(len(list(directory.glob("*.json"))), 2)
        self.assertEqual(first[0].read_bytes(), initial_bytes)

    def test_diagnostic_collision_refuses_overwrite(self) -> None:
        anchor = self.load_anchor()
        with patch.object(evaluation_common.uuid, "uuid4", return_value=SimpleNamespace(hex="0" * 32)):
            path = evaluation_common.preserve_execution_profile_discovery(
                anchor, self.profile, self.repository, "task"
            )
            original = path.read_bytes()
            with self.assertRaises(evaluation_common.EvaluationError):
                evaluation_common.preserve_execution_profile_discovery(
                    anchor, dict(self.profile, model_catalog_sha256="f" * 64), self.repository, "task"
                )
        self.assertEqual(path.read_bytes(), original)

    def test_private_writer_refuses_public_path_and_existing_entry(self) -> None:
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.write_private_profile_json_exclusive(
                self.root / "public.json", {"private": "metadata"}
            )
        path = self.private / "private.json"
        evaluation_common.write_private_profile_json_exclusive(path, {"first": True})
        original = path.read_bytes()
        with self.assertRaises(evaluation_common.EvaluationError):
            evaluation_common.write_private_profile_json_exclusive(path, {"first": False})
        self.assertEqual(path.read_bytes(), original)

    def test_discovery_sink_refuses_reparse_directory(self) -> None:
        anchor = self.load_anchor()
        directory = self.private / "anchor.json.discoveries"
        directory.mkdir()
        original_lstat = Path.lstat

        def reparse_lstat(candidate: Path, *args, **kwargs):
            if candidate == directory:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400)
            return original_lstat(candidate, *args, **kwargs)

        with patch.object(Path, "lstat", reparse_lstat):
            with self.assertRaises(evaluation_common.EvaluationError):
                evaluation_common.preserve_execution_profile_discovery(
                    anchor, self.profile, self.repository, "task"
                )
        self.assertEqual(list(directory.iterdir()), [])

    def test_native_profile_retains_exact_selected_snapshot_without_live_probes(self) -> None:
        native = self.private / "synthetic-native.bin"
        native.write_bytes(b"MZ synthetic native fixture; must never execute")
        metadata = selected_metadata()
        catalog_text = json.dumps({"models": [metadata, {"slug": "unrelated"}]})
        prompt_receipt = {
            "method": evaluation_common.MODEL_PROMPT_ISOLATION_PROBE_METHOD,
            "schema": evaluation_common.MODEL_PROMPT_ISOLATION_PROBE_SCHEMA,
            "sha256": "e" * 64,
        }
        with (
            patch.object(
                evaluation_common.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess([], 0, "codex-cli synthetic\n", ""),
                    subprocess.CompletedProcess([], 0, catalog_text, ""),
                ],
            ) as native_probes,
            patch.object(
                evaluation_common, "_codex_model_isolation_prompt_probe", return_value=prompt_receipt
            ) as prompt_probe,
        ):
            actual = evaluation_common.codex_execution_profile(
                str(native), "gpt-6.1-sol", "ultra"
            )
        self.assertEqual(native_probes.call_count, 2)
        self.assertEqual(prompt_probe.call_count, 1)
        self.assertEqual(actual["selected_model_metadata"], metadata)
        self.assertEqual(actual["selected_model_sha256"], selected_digest(metadata))
        self.assertEqual(
            actual["model_catalog_sha256"], hashlib.sha256(catalog_text.encode("utf-8")).hexdigest()
        )
        self.assertNotIn("models", actual)

    def driver_arguments(self, module, *, execute: bool = True) -> list[str]:
        arguments = [module.__name__ + ".py"]
        if module in (grade_behavioral_benchmark, run_blind_comparisons):
            arguments.append(str(self.root / "synthetic-input" / module.__name__))
        else:
            arguments.extend([
                "--output-root", str(self.root / "synthetic-output" / module.__name__),
                "--run-id", "fresh-offline-test",
            ])
        if module is not run_gate1_evidence:
            arguments.append("--execute" if execute else "--dry-run")
        if module is run_gate1_evidence and execute:
            arguments.append("--execute")
        if module is not run_gate1_evidence and execute:
            arguments.extend(["--model", "gpt-6.1-sol", "--reasoning-effort", "ultra"])
        return arguments

    def mock_driver_inputs(self, stack: ExitStack, module) -> None:
        if module in (run_behavioral_benchmark, run_trigger_evals):
            stack.enter_context(patch.object(module, "baseline_contamination_paths", return_value=[]))
            stack.enter_context(patch.object(module, "tracked_directory_sha256", return_value="f" * 64))
        if module is grade_behavioral_benchmark:
            stack.enter_context(patch.object(
                module, "require_complete_task_evidence",
                return_value=[self.root / "synthetic-input" / module.__name__ / "runs" / "001"],
            ))
        if module is run_blind_comparisons:
            stack.enter_context(patch.object(module, "require_complete_task_evidence", return_value=[]))
            stack.enter_context(patch.object(module, "discover_pairs", return_value=[{
                "pair_id": "synthetic__r01", "case_id": "synthetic", "runs": {},
            }]))

    def forbidden_launches(self, stack: ExitStack, module) -> list:
        names = {
            run_behavioral_benchmark: ("run_one", "run_codex"),
            run_trigger_evals: ("run_trigger_prediction",),
            grade_behavioral_benchmark: ("run_codex",),
            run_blind_comparisons: ("run_codex",),
            run_gate1_evidence: ("run_gate1_model_sequence", "_run_stage_command"),
        }[module]
        return [stack.enter_context(patch.object(
            module, name, side_effect=AssertionError("a rejected preflight must not launch a model")
        )) for name in names]

    def test_all_execute_drivers_reject_missing_or_bad_anchor_before_discovery(self) -> None:
        path, digest = self.write_anchor()
        variants = (
            [],
            ["--profile-anchor", str(path)],
            ["--profile-anchor-sha256", digest],
            ["--profile-anchor", str(path), "--profile-anchor-sha256", "f" * 64],
        )
        for module in (
            run_behavioral_benchmark, run_trigger_evals,
            grade_behavioral_benchmark, run_blind_comparisons, run_gate1_evidence,
        ):
            for flags in variants:
                with self.subTest(module=module.__name__, flags=flags), ExitStack() as stack:
                    stack.enter_context(patch.object(sys, "argv", self.driver_arguments(module) + flags))
                    find = stack.enter_context(patch.object(
                        module, "find_codex_command", side_effect=AssertionError("native discovery must not run")
                    ))
                    discover = stack.enter_context(patch.object(
                        module, "codex_execution_profile", side_effect=AssertionError("native probe must not run")
                    ))
                    launches = self.forbidden_launches(stack, module)
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    stack.enter_context(redirect_stderr(io.StringIO()))
                    self.assertEqual(module.main(), 2)
                    find.assert_not_called()
                    discover.assert_not_called()
                    for launch in launches:
                        launch.assert_not_called()
        self.assertFalse((self.root / "synthetic-input").exists())
        self.assertFalse((self.root / "synthetic-output").exists())
        self.assertFalse((self.private / "anchor.json.discoveries").exists())
        self.subprocess_mock.assert_not_called()

    def test_all_execute_drivers_reject_each_identity_drift_before_model_or_output(self) -> None:
        changes = [(key, "f" * 64 if key.endswith("sha256") else "different") for key in PROFILE_IDENTITY_KEYS]
        for module in (
            run_behavioral_benchmark, run_trigger_evals,
            grade_behavioral_benchmark, run_blind_comparisons, run_gate1_evidence,
        ):
            for index, (key, value) in enumerate(changes):
                with self.subTest(module=module.__name__, key=key), ExitStack() as stack:
                    name = f"{module.__name__}-{index}-anchor.json"
                    path, digest = self.write_anchor(name=name)
                    actual = copy.deepcopy(self.profile)
                    actual[key] = value
                    flags = ["--profile-anchor", str(path), "--profile-anchor-sha256", digest]
                    stack.enter_context(patch.object(sys, "argv", self.driver_arguments(module) + flags))
                    self.mock_driver_inputs(stack, module)
                    stack.enter_context(patch.object(module, "find_codex_command", return_value="never-launched"))
                    discover = stack.enter_context(patch.object(module, "codex_execution_profile", return_value=actual))
                    stack.enter_context(patch.object(module, "repository_receipt", return_value=self.repository))
                    launches = self.forbidden_launches(stack, module)
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    stack.enter_context(redirect_stderr(io.StringIO()))
                    self.assertEqual(module.main(), 2)
                    discover.assert_called_once()
                    for launch in launches:
                        launch.assert_not_called()
                    retained = list((path.parent / (path.name + ".discoveries")).glob("*.json"))
                    self.assertEqual(len(retained), 1)
                    diagnostic = json.loads(retained[0].read_text(encoding="utf-8"))
                    self.assertEqual(diagnostic["execution_profile"], actual)
                    self.assertEqual(diagnostic["repository"], self.repository)
                    self.assertIs(diagnostic["qualification_or_publication_authority"], False)
                    self.assertFalse((self.root / "synthetic-input").exists())
                    self.assertFalse((self.root / "synthetic-output").exists())
        self.subprocess_mock.assert_not_called()

    def test_trigger_anchor_mutated_inside_discovery_fails_without_launch_or_output(self) -> None:
        path, digest = self.write_anchor()

        def tamper_during_discovery(*_args):
            document = self.document()
            document["execution_profile"]["model_catalog_sha256"] = "f" * 64
            path.write_text(json.dumps(document) + "\n", encoding="utf-8")
            return self.profile

        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", self.driver_arguments(run_trigger_evals) + [
                "--profile-anchor", str(path), "--profile-anchor-sha256", digest,
            ]))
            self.mock_driver_inputs(stack, run_trigger_evals)
            stack.enter_context(patch.object(run_trigger_evals, "find_codex_command", return_value="never-launched"))
            stack.enter_context(patch.object(run_trigger_evals, "codex_execution_profile", side_effect=tamper_during_discovery))
            stack.enter_context(patch.object(run_trigger_evals, "repository_receipt", return_value=self.repository))
            launches = self.forbidden_launches(stack, run_trigger_evals)
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            self.assertEqual(run_trigger_evals.main(), 2)
            for launch in launches:
                launch.assert_not_called()
        self.assertFalse((self.root / "synthetic-output").exists())
        self.assertEqual(len(list((self.private / "anchor.json.discoveries").glob("*.json"))), 1)

    def test_all_drivers_retain_dirty_actual_repository_before_refusal(self) -> None:
        dirty = dict(self.repository, dirty=True)
        for module in (
            run_behavioral_benchmark, run_trigger_evals,
            grade_behavioral_benchmark, run_blind_comparisons, run_gate1_evidence,
        ):
            with self.subTest(module=module.__name__), ExitStack() as stack:
                path, digest = self.write_anchor(name=f"{module.__name__}-dirty-anchor.json")
                stack.enter_context(patch.object(sys, "argv", self.driver_arguments(module) + [
                    "--profile-anchor", str(path), "--profile-anchor-sha256", digest,
                ]))
                self.mock_driver_inputs(stack, module)
                stack.enter_context(patch.object(module, "find_codex_command", return_value="never-launched"))
                discover = stack.enter_context(patch.object(module, "codex_execution_profile", return_value=self.profile))

                def repository_probe(require_clean=False):
                    if require_clean:
                        raise evaluation_common.EvaluationError("synthetic dirty checkout")
                    return dirty

                stack.enter_context(patch.object(module, "repository_receipt", side_effect=repository_probe))
                launches = self.forbidden_launches(stack, module)
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(redirect_stderr(io.StringIO()))
                self.assertEqual(module.main(), 2)
                discover.assert_called_once()
                for launch in launches:
                    launch.assert_not_called()
                retained = list((path.parent / (path.name + ".discoveries")).glob("*.json"))
                self.assertEqual(len(retained), 1)
                document = json.loads(retained[0].read_text(encoding="utf-8"))
                self.assertEqual(document["execution_profile"], self.profile)
                self.assertEqual(document["repository"], dirty)
                self.assertFalse((self.root / "synthetic-input").exists())
                self.assertFalse((self.root / "synthetic-output").exists())

    def test_configured_model_or_effort_mismatch_refuses_before_discovery(self) -> None:
        for module in (
            run_behavioral_benchmark, run_trigger_evals,
            grade_behavioral_benchmark, run_blind_comparisons,
        ):
            for flag, value in (("--model", "different-model"), ("--reasoning-effort", "medium")):
                with self.subTest(module=module.__name__, flag=flag), ExitStack() as stack:
                    path, digest = self.write_anchor(name=f"{module.__name__}-{flag[2:]}-anchor.json")
                    arguments = self.driver_arguments(module)
                    arguments[arguments.index(flag) + 1] = value
                    arguments.extend(["--profile-anchor", str(path), "--profile-anchor-sha256", digest])
                    stack.enter_context(patch.object(sys, "argv", arguments))
                    discover = stack.enter_context(patch.object(
                        module, "codex_execution_profile", side_effect=AssertionError("configured mismatch must not probe")
                    ))
                    find = stack.enter_context(patch.object(
                        module, "find_codex_command", side_effect=AssertionError("configured mismatch must not discover")
                    ))
                    launches = self.forbidden_launches(stack, module)
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    stack.enter_context(redirect_stderr(io.StringIO()))
                    self.assertEqual(module.main(), 2)
                    discover.assert_not_called()
                    find.assert_not_called()
                    for launch in launches:
                        launch.assert_not_called()
                    self.assertFalse((path.parent / (path.name + ".discoveries")).exists())
        self.assertFalse((self.root / "synthetic-input").exists())
        self.assertFalse((self.root / "synthetic-output").exists())

    def test_gate1_fixed_request_rejects_different_anchor_before_discovery(self) -> None:
        for field in ("model", "reasoning_effort"):
            with self.subTest(field=field), ExitStack() as stack:
                document = self.document()
                profile = document["execution_profile"]
                if field == "model":
                    profile["model"] = "synthetic-different-model"
                    profile["selected_model_metadata"]["slug"] = profile["model"]
                else:
                    profile["reasoning_effort"] = "medium"
                    profile["selected_model_metadata"]["supported_reasoning_levels"].append({"effort": "medium"})
                profile["selected_model_sha256"] = selected_digest(profile["selected_model_metadata"])
                path, digest = self.write_anchor(document, name=f"gate1-{field}-anchor.json")
                stack.enter_context(patch.object(sys, "argv", self.driver_arguments(run_gate1_evidence) + [
                    "--profile-anchor", str(path), "--profile-anchor-sha256", digest,
                ]))
                discover = stack.enter_context(patch.object(
                    run_gate1_evidence, "codex_execution_profile",
                    side_effect=AssertionError("Gate 1 configured mismatch must not probe"),
                ))
                find = stack.enter_context(patch.object(
                    run_gate1_evidence, "find_codex_command",
                    side_effect=AssertionError("Gate 1 configured mismatch must not discover"),
                ))
                launches = self.forbidden_launches(stack, run_gate1_evidence)
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(redirect_stderr(io.StringIO()))
                self.assertEqual(run_gate1_evidence.main(), 2)
                discover.assert_not_called()
                find.assert_not_called()
                for launch in launches:
                    launch.assert_not_called()
                self.assertFalse((path.parent / (path.name + ".discoveries")).exists())
        self.assertFalse((self.root / "synthetic-output").exists())

    def test_all_driver_dry_runs_need_no_anchor_and_write_nothing_or_probe(self) -> None:
        original = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        for module in (
            run_behavioral_benchmark, run_trigger_evals,
            grade_behavioral_benchmark, run_blind_comparisons, run_gate1_evidence,
        ):
            with self.subTest(module=module.__name__), ExitStack() as stack:
                stack.enter_context(patch.object(sys, "argv", self.driver_arguments(module, execute=False)))
                self.mock_driver_inputs(stack, module)
                anchor = stack.enter_context(patch.object(module, "load_execution_profile_anchor", side_effect=AssertionError("dry-run must not load an anchor")))
                discover = stack.enter_context(patch.object(module, "codex_execution_profile", side_effect=AssertionError("dry-run must not probe a native")))
                launches = self.forbidden_launches(stack, module)
                output = io.StringIO()
                stack.enter_context(redirect_stdout(output))
                stack.enter_context(redirect_stderr(io.StringIO()))
                self.assertEqual(module.main(), 0)
                self.assertEqual(json.loads(output.getvalue())["mode"], "dry-run")
                anchor.assert_not_called()
                discover.assert_not_called()
                for launch in launches:
                    launch.assert_not_called()
        current = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(current, original)
        self.subprocess_mock.assert_not_called()

    def capture_arguments(self, path: Path) -> list[str]:
        return [
            "capture_evaluation_profile.py", "--output", str(path),
            "--codex-command", "never-launched", "--model", "gpt-6.1-sol",
            "--reasoning-effort", "ultra",
        ]

    def test_capture_cli_writes_exact_private_technical_anchor_with_no_model_calls(self) -> None:
        path = self.private / "captured.json"
        output = io.StringIO()
        with (
            patch.object(sys, "argv", self.capture_arguments(path)),
            patch.object(capture_evaluation_profile, "find_codex_command", return_value="never-launched"),
            patch.object(capture_evaluation_profile, "codex_execution_profile", return_value=self.profile) as capture,
            patch.object(capture_evaluation_profile, "repository_receipt", return_value=self.repository),
            redirect_stdout(output),
        ):
            self.assertEqual(capture_evaluation_profile.main(), 0)
        capture.assert_called_once_with("never-launched", "gpt-6.1-sol", "ultra")
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["profile_anchor_sha256"], evaluation_common.file_sha256(path))
        self.assertEqual(receipt["model_calls"], 0)
        self.assertIs(receipt["qualification_or_publication_authority"], False)
        anchor = evaluation_common.load_execution_profile_anchor(path, receipt["profile_anchor_sha256"])
        self.assertEqual(anchor["execution_profile"], self.profile)
        self.assertEqual(anchor["repository"], self.repository)
        self.subprocess_mock.assert_not_called()

    def test_capture_cli_refuses_existing_or_public_target_before_probe(self) -> None:
        existing, _ = self.write_anchor()
        original = existing.read_bytes()
        for path in (existing, self.root / "public-capture.json"):
            with self.subTest(path=path), ExitStack() as stack:
                stack.enter_context(patch.object(sys, "argv", self.capture_arguments(path)))
                capture = stack.enter_context(patch.object(
                    capture_evaluation_profile, "codex_execution_profile",
                    side_effect=AssertionError("invalid sink must not probe"),
                ))
                stack.enter_context(redirect_stdout(io.StringIO()))
                self.assertEqual(capture_evaluation_profile.main(), 2)
                capture.assert_not_called()
        self.assertEqual(existing.read_bytes(), original)
        self.assertFalse((self.root / "public-capture.json").exists())


if __name__ == "__main__":
    unittest.main()
