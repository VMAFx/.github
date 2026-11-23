# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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


class FakeGh:
    def __init__(
        self,
        *,
        list_payload: list[dict] | None = None,
        get_sequence: list[dict] | None = None,
        fail: Exception | None = None,
        bad_json: bool = False,
        history: list[int] | None = None,
        foreign_writes: dict[int, list[tuple[str, dict]]] | None = None,
        put_adds_version: bool = True,
        bad_history: bool = False,
        own_state_change: dict | None = None,
        stateless_foreign: bool = False,
    ) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        if list_payload is None:
            self.list_payload = [{"id": 7, "name": TOP["name"]}]
        else:
            self.list_payload = list_payload
        self.get_sequence = list(get_sequence) if get_sequence is not None else [LIVE]
        self.fail = fail
        self.bad_json = bad_json
        self.history = list(history) if history is not None else [100]
        self.foreign_writes = foreign_writes
        self.put_adds_version = put_adds_version
        self.bad_history = bad_history
        self.own_state_change = own_state_change
        self.stateless_foreign = stateless_foreign
        self.states: dict[int, dict] = {}
        self.put_count = 0

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        self.calls.append((list(args), stdin))
        if self.fail is not None:
            raise self.fail
        if args[:4] == ["repo", "view", "--json", "nameWithOwner"]:
            return "VMAFx/.github\n"
        if args[:3] == ["api", "-X", "PUT"] and args[-2:] == ["--input", "-"]:
            return self._put(stdin)
        if len(args) == 2 and args[0] == "api":
            return self._api_get(args)
        raise AssertionError(f"unexpected gh call: {args!r}, stdin={stdin!r}")

    def _api_get(self, args: list[str]) -> str:
        path = args[1]
        if path.startswith("repos/") and "/rulesets?" in path:
            return "not json" if self.bad_json else json.dumps(self.list_payload)
        if "/history/" in path and "?" not in path:
            return self._version_payload(path)
        if "/history?" in path:
            return self._history_payload()
        if "/rulesets/" in path and "?" not in path:
            if not self.get_sequence:
                raise AssertionError(f"unexpected ruleset GET: {args!r}")
            return json.dumps(self.get_sequence.pop(0))
        raise AssertionError(f"unexpected gh call: {args!r}, stdin=None")

    def _version_payload(self, path: str) -> str:
        version_id = int(path.rsplit("/", 1)[-1])
        if version_id not in self.states:
            return json.dumps({"version_id": version_id})
        return json.dumps(
            {
                "version_id": version_id,
                "actor": {"id": 1, "type": "User"},
                "updated_at": "2026-11-22T00:00:00Z",
                "state": self.states[version_id],
            }
        )

    def _history_payload(self) -> str:
        if self.bad_history:
            return "{}"
        entries = [
            {
                "version_id": version,
                "actor": {"id": 1, "type": "User"},
                "updated_at": "2026-11-22T00:00:00Z",
            }
            for version in reversed(self.history)
        ]
        return json.dumps(entries)

    def _append_version(self, state: dict | None) -> int:
        new_id = max(self.history, default=0) + 1
        self.history.append(new_id)
        if state is not None:
            self.states[new_id] = state
        return new_id

    def _put(self, stdin: str | None) -> str:
        put_index = self.put_count
        self.put_count += 1
        entries = (self.foreign_writes or {}).get(put_index, [])
        for when, state in entries:
            if when == "before":
                if state is None and self.stateless_foreign:
                    self._append_version(None)
                else:
                    self._append_version(state)
        if self.put_adds_version:
            payload = json.loads(stdin or "{}")
            own_state = {**payload, **(self.own_state_change or {})}
            self._append_version(own_state)
        for when, state in entries:
            if when == "after":
                self._append_version(state)
        return "{}"


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

    def test_two_foreign_versions_fail_closed(self) -> None:
        foreign_a = json.loads(json.dumps(LIVE))
        foreign_a["rules"].append({"type": "creation"})
        foreign_b = json.loads(json.dumps(LIVE))
        foreign_b["rules"].append({"type": "update"})
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, merged_live()],
                foreign_writes={
                    0: [("before", foreign_a), ("before", foreign_b)],
                },
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)
            self.assertIn("101", err)
            self.assertIn("102", err)
            self.assertIn("history/<version_id>", err)

    def test_foreign_write_before_put_is_restored(self) -> None:
        foreign = json.loads(json.dumps(LIVE))
        foreign["rules"].append({"type": "creation"})
        merged_again = apply_ruleset.merge_ruleset(foreign, DECLARED)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, merged_live(), merged_again],
                foreign_writes={0: [("before", foreign)]},
            )
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 2)
            payload = json.loads(puts[1][1] or "{}")
            types = {rule["type"] for rule in payload["rules"]}
            self.assertIn("creation", types)
            for rule in DECLARED["rules"]:
                self.assertIn(rule["type"], types)
            self.assertIn("writing again", out)
            self.assertIn("101", out)

    def test_foreign_write_after_put_is_restored(self) -> None:
        foreign = merged_live()
        foreign["rules"] = [
            r for r in foreign["rules"] if r["type"] != "copilot_code_review"
        ]
        merged_again = apply_ruleset.merge_ruleset(foreign, DECLARED)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, foreign, merged_again],
                foreign_writes={0: [("after", foreign)]},
            )
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 2)
            payload = json.loads(puts[1][1] or "{}")
            types = {rule["type"] for rule in payload["rules"]}
            self.assertIn("copilot_code_review", types)

    def test_foreign_version_equal_to_write_is_accepted(self) -> None:
        foreign = merged_live()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, merged_live()],
                foreign_writes={0: [("before", foreign)]},
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 0, msg=err)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)

    def test_foreign_writes_every_round_fail_closed(self) -> None:
        foreign = json.loads(json.dumps(LIVE))
        foreign["rules"].append({"type": "creation"})
        merged_after = apply_ruleset.merge_ruleset(foreign, DECLARED)
        rounds = apply_ruleset.MAX_WRITE_ROUNDS
        get_sequence = [LIVE, LIVE]
        for _ in range(rounds):
            get_sequence.extend([merged_live(), merged_after])
        foreign_map = {n: [("before", foreign)] for n in range(rounds)}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=get_sequence,
                foreign_writes=foreign_map,
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), rounds)
            self.assertIn(str(rounds), err)
            self.assertIn("history/<version_id>", err)

    def test_own_version_not_found_fails_closed(self) -> None:
        foreign = json.loads(json.dumps(LIVE))
        foreign["rules"].append({"type": "creation"})
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, merged_live()],
                foreign_writes={0: [("before", foreign)]},
                own_state_change={"enforcement": "evaluate"},
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)
            self.assertIn("cannot find this write", err)

    def test_version_without_state_fails_closed(self) -> None:
        foreign = json.loads(json.dumps(LIVE))
        foreign["rules"].append({"type": "creation"})
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, merged_live()],
                foreign_writes={0: [("before", None)]},
                stateless_foreign=True,
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            puts = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)
            self.assertIn("has no state object", err)

    def test_write_without_new_history_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(
                get_sequence=[LIVE, LIVE, merged_live()],
                put_adds_version=False,
            )
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertIn("no new version", err)

    def test_unreadable_history_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[LIVE, LIVE, merged_live()], bad_history=True)
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertNotEqual(err, "")
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(puts, [])

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
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[LIVE, LIVE, LIVE])
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path), "--apply"],
                gh,
            )
            self.assertEqual(rc, 1)
            self.assertNotEqual(err, "")

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


if __name__ == "__main__":
    unittest.main()
