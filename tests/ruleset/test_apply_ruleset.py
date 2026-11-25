# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "apply-ruleset.py"

SPEC = importlib.util.spec_from_file_location("apply_ruleset", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
apply_ruleset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apply_ruleset)

TOP = {
    "bypass_actors": [
        {
            "actor_id": 5,
            "actor_type": "RepositoryRole",
            "bypass_mode": "pull_request",
        }
    ],
    "conditions": {
        "ref_name": {
            "exclude": [],
            "include": ["refs/heads/master", "refs/heads/lts-*"],
        }
    },
    "enforcement": "active",
    "name": "praetor-main-protection",
    "target": "branch",
}

LIVE = {
    **TOP,
    "id": 7,
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        {"type": "required_signatures"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews_on_push": True,
                "required_review_thread_resolution": True,
                "require_extra_approval_for_unattributed_changes": True,
            },
        },
    ],
}

DECLARED = {
    **TOP,
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        {"type": "required_signatures"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews_on_push": True,
                "required_review_thread_resolution": True,
            },
        },
        {
            "type": "copilot_code_review",
            "parameters": {
                "review_draft_pull_requests": True,
                "review_on_push": True,
            },
        },
    ],
}


def merged_live() -> dict:
    return apply_ruleset.merge_ruleset(LIVE, DECLARED)


HISTORY_POINTER = (
    "inspect each version with gh api repos/VMAFx/.github/rulesets/7/history/"
    "<version_id>, restore the intended state, then re-run\n"
)


class FakeGh:
    def __init__(
        self,
        *,
        list_payload: list[dict] | None = None,
        get_sequence: list[dict | Exception] | None = None,
        fail: Exception | None = None,
        bad_json: bool = False,
        history_sequence: list[list[int] | Exception] | None = None,
    ) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        if list_payload is None:
            self.list_payload = [{"id": 7, "name": TOP["name"]}]
        else:
            self.list_payload = list_payload
        self.get = Mock(side_effect=get_sequence if get_sequence is not None else [LIVE])
        self.fail = fail
        self.bad_json = bad_json
        if history_sequence is None:
            history_sequence = [[97], [4101, 97]]
        self.history = Mock(side_effect=history_sequence)
        self.put = Mock(return_value="{}")

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        self.calls.append((list(args), stdin))
        if self.fail is not None:
            raise self.fail
        if args[:4] == ["repo", "view", "--json", "nameWithOwner"]:
            return "VMAFx/.github\n"
        if args[:3] == ["api", "-X", "PUT"] and args[-2:] == ["--input", "-"]:
            return self.put(stdin)
        if len(args) == 2 and args[0] == "api":
            return self._api_get(args)
        raise AssertionError(f"unexpected gh call: {args!r}, stdin={stdin!r}")

    def _api_get(self, args: list[str]) -> str:
        path = args[1]
        if path.startswith("repos/") and "/rulesets?" in path:
            return "not json" if self.bad_json else json.dumps(self.list_payload)
        if path == "repos/VMAFx/.github/rulesets/7/history?per_page=100":
            return json.dumps([{"version_id": version} for version in self.history()])
        if path == "repos/VMAFx/.github/rulesets/7":
            return json.dumps(self.get())
        raise AssertionError(f"unexpected gh call: {args!r}, stdin=None")


def write_json(directory: str, name: str, payload: dict) -> Path:
    path = Path(directory) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def run_main(
    argv: list[str],
    gh: FakeGh,
) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = apply_ruleset.main(argv, gh=gh)
    return rc, out.getvalue(), err.getvalue()


class ApplyRulesetTests(unittest.TestCase):
    def test_dry_run_reports_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh()
            rc, out, _ = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 0)
            self.assertIn("copilot_code_review", out)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_apply_merges_and_reads_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            merged = merged_live()
            gh = FakeGh(get_sequence=[LIVE, LIVE, merged])
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)
            payload = json.loads(puts[0][1] or "{}")
            types = {rule["type"] for rule in payload["rules"]}
            self.assertIn("copilot_code_review", types)
            pull = next(
                rule for rule in payload["rules"] if rule["type"] == "pull_request"
            )
            self.assertTrue(
                pull["parameters"]["require_extra_approval_for_unattributed_changes"]
            )
            self.assertIn("declared rules match", out)

    def test_apply_reads_history_around_the_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[LIVE, LIVE, merged_live()])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            history_calls = [
                i
                for i, (args, _) in enumerate(gh.calls)
                if len(args) == 2 and args[0] == "api" and "/history?" in args[1]
            ]
            self.assertEqual(history_calls, [2, 6])
            ruleset_gets = [
                i
                for i, (args, _) in enumerate(gh.calls)
                if len(args) == 2
                and args[0] == "api"
                and "/rulesets/" in args[1]
                and "?" not in args[1]
            ]
            put_idx = next(
                i
                for i, (args, _) in enumerate(gh.calls)
                if args[:3] == ["api", "-X", "PUT"]
            )
            self.assertLess(history_calls[0], ruleset_gets[1])
            self.assertGreater(history_calls[1], put_idx)

    def assert_apply_failure(self, gh: FakeGh, reason: str, put_count: int) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"], gh
            )
        self.assertEqual(rc, 1)
        self.assertEqual(gh.put.call_count, put_count)
        self.assertEqual(err, reason + "\n" + HISTORY_POINTER)

    def test_foreign_write_before_put_stops(self) -> None:
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, merged_live()],
            history_sequence=[[97], [7303, 4101, 97]],
        )
        self.assert_apply_failure(
            gh, "ruleset history shows 2 new versions (4101, 7303)", 1
        )

    def test_foreign_write_after_put_reports_mismatch(self) -> None:
        foreign = merged_live()
        foreign["rules"] = [
            rule for rule in foreign["rules"] if rule["type"] != "copilot_code_review"
        ]
        foreign["rules"].append({"type": "creation"})
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, foreign],
            history_sequence=[[97], [7303, 4101, 97]],
        )
        self.assert_apply_failure(
            gh,
            "rule copilot_code_review: missing after read-back\n"
            "ruleset history shows 2 new versions (4101, 7303)",
            1,
        )

    def test_unreadable_history_writes_nothing(self) -> None:
        gh = FakeGh(history_sequence=[apply_ruleset.GhError("history failed")])
        self.assert_apply_failure(gh, "history unreadable: history failed", 0)
        gh.get.assert_called_once()

    def test_failed_fresh_get_writes_nothing(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, apply_ruleset.GhError("fresh GET failed")])
        self.assert_apply_failure(gh, "fresh GET failed", 0)
        gh.history.assert_called_once()

    def test_failed_put_reports_history_endpoint(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE])
        gh.put.side_effect = apply_ruleset.GhError("PUT failed")
        self.assert_apply_failure(gh, "PUT failed", 1)

    def test_failed_readback_reports_new_version(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE, apply_ruleset.GhError("GET failed")])
        self.assert_apply_failure(
            gh, "GET failed\nruleset history shows 1 new version (4101)", 1
        )

    def test_failed_history_after_put_reports_error(self) -> None:
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, merged_live()],
            history_sequence=[[97], apply_ruleset.GhError("history failed")],
        )
        self.assert_apply_failure(gh, "history unreadable: history failed", 1)

    def test_write_without_new_history_version_fails(self) -> None:
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, merged_live()], history_sequence=[[97], [97]]
        )
        self.assert_apply_failure(
            gh, "ruleset history shows no new version after the write", 1
        )

    def test_dry_run_reads_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh()
            rc, _, _ = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 0)
            history_calls = [call for call in gh.calls if "/history" in call[0][1]]
            self.assertEqual(history_calls, [])

    def test_live_only_rule_is_kept(self) -> None:
        live = json.loads(json.dumps(LIVE))
        live["rules"].append({"type": "creation"})
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            merged = apply_ruleset.merge_ruleset(live, DECLARED)
            gh = FakeGh(get_sequence=[live, live, merged])
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            payload = json.loads(puts[0][1] or "{}")
            types = {rule["type"] for rule in payload["rules"]}
            self.assertIn("creation", types)
            self.assertIn("kept live rule not in the file: creation", out)

    def test_already_matching_writes_nothing(self) -> None:
        merged = merged_live()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[merged])
            rc, out, _ = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 0)
            self.assertIn("already matches", out)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_readback_mismatch_fails(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE, LIVE])
        self.assert_apply_failure(
            gh,
            "rule copilot_code_review: missing after read-back\n"
            "ruleset history shows 1 new version (4101)",
            1,
        )

    def test_missing_ruleset_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(list_payload=[])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("no live ruleset", err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_duplicate_ruleset_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                list_payload=[
                    {"id": 7, "name": TOP["name"]},
                    {"id": 8, "name": TOP["name"]},
                ]
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("more than one live ruleset", err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_non_json_api_answer_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(bad_json=True)
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertNotEqual(err, "")
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_gh_failure_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(fail=apply_ruleset.GhError("list failed"))
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("list failed", err)

    def test_live_change_since_snapshot_writes_nothing(self) -> None:
        snapshot = json.loads(json.dumps(LIVE))
        snapshot["rules"] = [
            r for r in snapshot["rules"] if r["type"] != "required_signatures"
        ]
        re_read = json.loads(json.dumps(LIVE))
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[snapshot, re_read])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("changed since it was read", err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_live_change_in_top_level_field_writes_nothing(self) -> None:
        re_read = json.loads(json.dumps(LIVE))
        re_read["bypass_actors"] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[LIVE, re_read])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("changed since it was read", err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

    def test_readback_missing_live_only_rule_fails(self) -> None:
        live = json.loads(json.dumps(LIVE))
        live["rules"].append({"type": "creation"})
        readback = json.loads(json.dumps(live))
        readback["rules"] = [r for r in readback["rules"] if r["type"] != "creation"]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[live, live, readback])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn(
                "live-only rule from the snapshot missing after read-back", err
            )

    def test_readback_changed_live_only_parameters_fails(self) -> None:
        live = json.loads(json.dumps(LIVE))
        live["rules"].append(
            {
                "type": "creation",
                "parameters": {"enabled": True},
            }
        )
        readback = json.loads(json.dumps(live))
        creation = next(r for r in readback["rules"] if r["type"] == "creation")
        creation["parameters"] = {"enabled": False}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[live, live, readback])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("live-only parameters changed after read-back", err)

    def test_readback_lost_live_only_parameter_on_declared_rule_fails(self) -> None:
        readback = merged_live()
        pull_request = next(r for r in readback["rules"] if r["type"] == "pull_request")
        del pull_request["parameters"][
            "require_extra_approval_for_unattributed_changes"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[LIVE, LIVE, readback])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn(
                "rule pull_request: live-only parameter "
                "require_extra_approval_for_unattributed_changes changed after read-back",
                err,
            )

    def test_server_metadata_change_still_writes(self) -> None:
        re_read = {**LIVE, "id": 99, "updated_at": "2026-01-01T00:00:00Z"}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            merged = merged_live()
            gh = FakeGh(get_sequence=[LIVE, re_read, merged])
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)
            self.assertIn("declared rules match", out)

    def test_malformed_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = {**TOP}
            path = write_json(tmp, "ruleset.json", broken)
            gh = FakeGh()
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("rules", err)
            self.assertEqual(gh.calls, [])


class RunGhTests(unittest.TestCase):
    def test_timeout_and_launch_error_include_command_and_cause(self) -> None:
        cmd = ["gh", "api", "repos/VMAFx/.github/rulesets/7"]
        for cause in (subprocess.TimeoutExpired(cmd, 60), FileNotFoundError("no gh")):
            with self.subTest(cause=cause):
                with (
                    patch.object(subprocess, "run", side_effect=cause),
                    self.assertRaises(apply_ruleset.GhError) as raised,
                ):
                    apply_ruleset.run_gh(cmd[1:])
                self.assertEqual(str(raised.exception), f"command: {cmd!r}\n{cause}")
                self.assertIs(raised.exception.__cause__, cause)

    def test_keyboard_interrupt_passes_through(self) -> None:
        interrupt = KeyboardInterrupt()
        with (
            patch.object(subprocess, "run", side_effect=interrupt),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            apply_ruleset.run_gh(["api", "repos/VMAFx/.github/rulesets/7"])
        self.assertIs(raised.exception, interrupt)


if __name__ == "__main__":
    unittest.main()
