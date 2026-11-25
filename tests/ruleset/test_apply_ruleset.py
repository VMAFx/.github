# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2

from __future__ import annotations

import importlib.util
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

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
WRITING = (
    "writing ruleset praetor-main-protection (7); version history: " + HISTORY_POINTER
)
REFUSAL_LINE = (
    "live ruleset praetor-main-protection (7) changed since it was read; "
    "nothing written; re-run to merge against the current state"
)
SNAPSHOT_REFUSAL = REFUSAL_LINE + "\nruleset history shows 1 new version (4101)"
NO_NEW_VERSION = "ruleset history shows no new version since the initial history read"


class FakeGh:
    def __init__(
        self,
        *,
        list_payload: list[dict] | None = None,
        get_sequence: list[dict | list | str | BaseException] | None = None,
        fail: Exception | None = None,
        bad_json: bool = False,
        history_sequence: list[list[int] | str | BaseException] | None = None,
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
        endpoint, _, page = path.partition("&page=")
        if endpoint == "repos/VMAFx/.github/rulesets/7/history?per_page=100":
            versions = self.history(int(page))
            if isinstance(versions, str):
                return versions
            return json.dumps([{"version_id": version} for version in versions])
        if path == "repos/VMAFx/.github/rulesets/7":
            body = self.get()
            return body if isinstance(body, str) else json.dumps(body)
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


def run_cli_with_fake_gh() -> None:
    gh = FakeGh(get_sequence=[LIVE, LIVE, merged_live()])

    def run(
        cmd: list[str], *, input: bytes | None, **kwargs
    ) -> subprocess.CompletedProcess:
        payload = input.decode() if input is not None else None
        reply = gh(cmd[1:], payload)
        return subprocess.CompletedProcess(cmd, 0, reply.encode(), b"")

    with patch.object(subprocess, "run", run):
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")


class LoadGhJsonTests(unittest.TestCase):
    def test_parser_failures_keep_cause(self) -> None:
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(4300)
        for body, cause in (
            ("[" * 200000, RecursionError),
            ("1" * 5000, ValueError),
            ("{", json.JSONDecodeError),
        ):
            with self.subTest(cause=cause.__name__):
                with self.assertRaises(apply_ruleset.GhError) as raised:
                    apply_ruleset._load_gh_json(body, "test response")
                exc = raised.exception
                self.assertIs(type(exc.__cause__), cause)
                self.assertEqual(
                    str(exc),
                    f"test response: unparseable JSON ({cause.__name__}): "
                    f"{exc.__cause__}",
                )

    def test_valid_object(self) -> None:
        self.assertEqual(apply_ruleset._load_gh_json(json.dumps(LIVE), "ruleset"), LIVE)


class ApplyRulesetTests(unittest.TestCase):
    def test_dry_run_reports_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh()
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(err, "")
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
            self.assertEqual(err, WRITING)
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
            self.assertEqual(err, WRITING)
            self.assertEqual(gh.put.call_count, 1)
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
        prefix = WRITING if put_count else ""
        self.assertEqual(err, prefix + reason + "\n" + HISTORY_POINTER)

    def test_deep_readback_reports_history(self) -> None:
        body = "[" * 200000
        with self.assertRaises(RecursionError) as parser:
            json.loads(body)
        self.assert_apply_failure(
            FakeGh(get_sequence=[LIVE, LIVE, body]),
            f"read-back failed: unparseable JSON (RecursionError): {parser.exception}\n"
            "ruleset history shows 1 new version (4101)",
            1,
        )

    def test_oversized_history_integer_reports_pointer(self) -> None:
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(4300)
        body = "1" * 5000
        with self.assertRaises(ValueError) as parser:
            json.loads(body)
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, merged_live()],
            history_sequence=[[97], body],
        )
        self.assert_apply_failure(
            gh,
            "history unreadable (GhError): ruleset history page 1: "
            f"unparseable JSON (ValueError): {parser.exception}",
            1,
        )

    def test_unexpected_readback_error_reports_history(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE, RuntimeError("lost reply")])
        self.assert_apply_failure(
            gh,
            "read-back failed (RuntimeError): lost reply\n"
            "ruleset history shows 1 new version (4101)",
            1,
        )

    def test_unexpected_history_error_reports_pointer(self) -> None:
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, merged_live()],
            history_sequence=[[97], RuntimeError("lost page")],
        )
        self.assert_apply_failure(gh, "history unreadable (RuntimeError): lost page", 1)

    def test_finding_3_history_uses_actual_cause_and_type(self) -> None:
        class HistoryFailure(apply_ruleset.GhError):
            @property
            def __cause__(self):
                raise ValueError("cannot read cause")

        class TransportFailure(Exception):
            @property
            def __class__(self):
                raise ValueError("cannot read class")

        for cause, label in (
            (ValueError(), "history unreadable (HistoryFailure)"),
            (TransportFailure(), "history unreadable"),
        ):
            with self.subTest(label=label):
                error = HistoryFailure("lost page")
                BaseException.__dict__["__cause__"].__set__(error, cause)
                gh = FakeGh(
                    get_sequence=[LIVE, LIVE, merged_live()],
                    history_sequence=[[97], error],
                )
                # unittest also follows __cause__ when rendering an escaped error.
                try:
                    self.assert_apply_failure(gh, f"{label}: lost page", 1)
                except ValueError as exc:
                    escaped = str(exc)
                else:
                    escaped = None
                self.assertIsNone(escaped)

    def test_finding_4_unprintable_gh_error_before_write(self) -> None:
        class LostReply(apply_ruleset.GhError):
            def __str__(self) -> str:
                raise ValueError("cannot format")

        detail = "LostReply (message unavailable: ValueError)"
        gh = FakeGh(history_sequence=[LostReply()])
        self.assert_apply_failure(gh, f"history unreadable: {detail}", 0)
        gh = FakeGh(fail=LostReply())
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            rc, _, err = run_main(["--file", str(path), "--apply"], gh)
        self.assertEqual((rc, err), (1, detail + "\n"))
        gh.put.assert_not_called()

    def test_finding_5_failed_put_with_closed_stderr(self) -> None:
        captured = io.StringIO()
        err = Mock(wraps=captured)
        gh = FakeGh()

        def fail_put(_: str) -> None:
            err.write.side_effect = BrokenPipeError("stderr closed")
            raise RuntimeError("lost PUT reply")

        gh.put.side_effect = fail_put
        with redirect_stderr(err):
            rc = apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        self.assertEqual(rc, 1)
        gh.put.assert_called_once()
        self.assertEqual(captured.getvalue(), WRITING)

    def test_finding_6_pointer_visible_at_put(self) -> None:
        err = io.StringIO()
        gh = FakeGh(get_sequence=[LIVE, merged_live()])

        def put(_: str) -> str:
            self.assertEqual(err.getvalue(), WRITING)
            return "{}"

        gh.put.side_effect = put
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        self.assertEqual(rc, 0, msg=err.getvalue())
        gh.put.assert_called_once()

    def test_finding_6_initial_history_runtime_error_propagates(self) -> None:
        gh = FakeGh(history_sequence=[RuntimeError("lost initial page")])
        with self.assertRaisesRegex(RuntimeError, "^lost initial page$"):
            apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        gh.put.assert_not_called()

    def test_unexpected_put_error_reports_history(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE])
        gh.put.side_effect = RuntimeError("lost PUT reply")
        self.assert_apply_failure(
            gh, "lost PUT reply\nruleset history shows 1 new version (4101)", 1
        )

    def test_write_interrupts_propagate(self) -> None:
        for interrupt in (KeyboardInterrupt(), SystemExit(2)):
            for stage in ("initial history", "put", "readback", "history"):
                with self.subTest(stage=stage, interrupt=type(interrupt).__name__):
                    gh = FakeGh(get_sequence=[LIVE, merged_live()])
                    if stage == "initial history":
                        gh.history.side_effect = interrupt
                    elif stage == "put":
                        gh.put.side_effect = interrupt
                    elif stage == "readback":
                        gh.get.side_effect = [LIVE, interrupt]
                    else:
                        gh.history.side_effect = [[97], interrupt]
                    err = io.StringIO()
                    with (
                        redirect_stderr(err),
                        self.assertRaises(type(interrupt)) as raised,
                    ):
                        apply_ruleset._write_and_verify(
                            gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
                        )
                    self.assertIs(raised.exception, interrupt)
                    put_count = 0 if stage == "initial history" else 1
                    self.assertEqual(gh.put.call_count, put_count)
                    self.assertEqual(err.getvalue(), WRITING if put_count else "")

    def test_unprintable_readback_error_reports_history(self) -> None:
        class LostReply(Exception):
            def __str__(self) -> str:
                raise ValueError("cannot format")

        gh = FakeGh(get_sequence=[LIVE, LIVE, LostReply()])
        self.assert_apply_failure(
            gh,
            "read-back failed (LostReply): LostReply "
            "(message unavailable: ValueError)\n"
            "ruleset history shows 1 new version (4101)",
            1,
        )

    def test_history_error_after_fresh_get_refusal_propagates(self) -> None:
        gh = FakeGh(
            get_sequence=[{**LIVE, "enforcement": "disabled"}],
            history_sequence=[[97], RuntimeError("lost page")],
        )
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaisesRegex(RuntimeError, "^lost page$"):
            apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        gh.put.assert_not_called()
        self.assertEqual(err.getvalue(), "")

    def test_unprintable_formatting_error_leaves_bare_name(self) -> None:
        class NoName(type):
            @property
            def __name__(cls) -> str:
                raise ValueError("cannot read class name")

        class FormattingError(Exception, metaclass=NoName):
            pass

        class LostReply(Exception):
            def __str__(self) -> str:
                raise FormattingError()

        self.assertEqual(apply_ruleset._describe(LostReply()), "LostReply")

    def test_unserializable_payload_writes_nothing(self) -> None:
        desired = merged_live()
        desired["rules"][-1]["parameters"]["bad"] = object()
        gh = FakeGh()
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(TypeError):
            apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, desired, DECLARED
            )
        gh.put.assert_not_called()
        self.assertEqual(err.getvalue(), "")

    def test_finding_2_cli_closed_pipe_returns_failure(self) -> None:
        launch = (
            "from tests.ruleset.test_apply_ruleset import run_cli_with_fake_gh; "
            "run_cli_with_fake_gh()"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            reader, writer = os.pipe()
            os.close(reader)
            with os.fdopen(writer, "wb") as pipe:
                result = subprocess.run(
                    [
                        sys.executable, "-E", "-B", "-c", launch, "--apply",
                        "--repo", "VMAFx/.github", "--file", str(path),
                    ],
                    cwd=REPO_ROOT,
                    stdout=pipe,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,
                )
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        self.assertEqual(
            result.stderr,
            WRITING + "could not write read-back result to stdout\n"
            "ruleset history shows 1 new version (4101)\n" + HISTORY_POINTER,
        )

    def test_finding_2_closed_stdout_reports_history(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, merged_live()])
        out = io.StringIO()
        out.close()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        self.assertEqual(rc, 1)
        gh.put.assert_called_once()
        self.assertEqual(
            err.getvalue(),
            WRITING + "could not write read-back result to stdout\n"
            "ruleset history shows 1 new version (4101)\n" + HISTORY_POINTER,
        )

    def test_broken_success_output_reports_history(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, merged_live()])
        out = Mock()
        out.write.side_effect = BrokenPipeError("pipe closed")
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        self.assertEqual(rc, 1)
        gh.put.assert_called_once()
        self.assertEqual(
            err.getvalue(),
            WRITING + "could not write read-back result to stdout\n"
            "ruleset history shows 1 new version (4101)\n" + HISTORY_POINTER,
        )

    def test_broken_success_output_and_stderr_return_failure(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, merged_live()])
        captured = io.StringIO()
        err = Mock(wraps=captured)

        def close_outputs(_: str) -> None:
            err.write.side_effect = BrokenPipeError("stderr closed")
            raise BrokenPipeError("stdout closed")

        out = Mock()
        out.write.side_effect = close_outputs
        with redirect_stdout(out), redirect_stderr(err):
            rc = apply_ruleset._write_and_verify(
                gh, "VMAFx/.github", 7, LIVE, merged_live(), DECLARED
            )
        self.assertEqual(rc, 1)
        gh.put.assert_called_once()
        self.assertEqual(captured.getvalue(), WRITING)

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
        self.assert_apply_failure(
            gh, "fresh GET failed\nruleset history shows 1 new version (4101)", 0
        )

    def test_failed_put_reports_history_endpoint(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE], history_sequence=[[4101], [4101]])
        gh.put.side_effect = apply_ruleset.GhError("PUT failed")
        self.assert_apply_failure(gh, f"PUT failed\n{NO_NEW_VERSION}", 1)

    def test_put_timeout_reports_new_version(self) -> None:
        gh = FakeGh(get_sequence=[LIVE, LIVE], history_sequence=[[4101], [7303, 4101]])
        gh.put.side_effect = apply_ruleset.GhError("PUT timed out")
        self.assert_apply_failure(
            gh, "PUT timed out\nruleset history shows 1 new version (7303)", 1
        )

    def test_malformed_readback_reports_new_version(self) -> None:
        cases = (
            ({"rules": None}, "rules must be a list"),
            ({}, "rules must be a list"),
            ({"rules": [None]}, "rules[0] must be an object"),
            ({"rules": [{"type": 1}]}, "rules[0] must have a string type"),
            ([], "expected an object"),
        )
        for readback, detail in cases:
            with self.subTest(readback=readback):
                gh = FakeGh(
                    get_sequence=[LIVE, LIVE, readback],
                    history_sequence=[[4101], [7303, 4101]],
                )
                self.assert_apply_failure(
                    gh,
                    f"malformed ruleset read-back: {detail}\n"
                    "ruleset history shows 1 new version (7303)",
                    1,
                )

    def test_failed_readback_and_history_report_both_errors(self) -> None:
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, apply_ruleset.GhError("GET failed")],
            history_sequence=[[4101], apply_ruleset.GhError("history failed")],
        )
        self.assert_apply_failure(
            gh, "GET failed\nhistory unreadable: history failed", 1
        )

    def test_reports_new_version_on_second_history_page(self) -> None:
        first_page = list(range(100))
        gh = FakeGh(
            get_sequence=[LIVE, LIVE, apply_ruleset.GhError("GET failed")],
            history_sequence=[
                first_page, [101, 102, 4101], first_page, [102, 4101, 7303]
            ],
        )
        self.assert_apply_failure(
            gh, "GET failed\nruleset history shows 1 new version (7303)", 1
        )
        self.assertEqual(
            gh.history.call_args_list, [call(1), call(2), call(1), call(2)]
        )

    def test_full_tenth_history_page_is_unreadable(self) -> None:
        full_pages = [list(range(start, start + 100)) for start in range(0, 1000, 100)]
        reason = "history unreadable: history longer than 10 pages"
        for put_count in (0, 1):
            with self.subTest(put_count=put_count):
                before = [[4101]] if put_count else []
                gh = FakeGh(
                    get_sequence=[LIVE, LIVE, merged_live()],
                    history_sequence=before + full_pages,
                )
                self.assert_apply_failure(gh, reason, put_count)
                initial_calls = [call(1)] if put_count else []
                self.assertEqual(
                    gh.history.call_args_list,
                    initial_calls + [call(page) for page in range(1, 11)],
                )

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
        self.assert_apply_failure(gh, NO_NEW_VERSION, 1)

    def test_dry_run_reads_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh()
            rc, _, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(err, "")
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
            self.assertEqual(err, WRITING)
            puts = [call for call in gh.calls if call[0][:3] == ["api", "-X", "PUT"]]
            self.assertEqual(len(puts), 1)
            payload = json.loads(puts[0][1] or "{}")
            types = {rule["type"] for rule in payload["rules"]}
            self.assertIn("creation", types)
            self.assertIn("kept live rule not in the file: creation", out)

    def test_already_matching_writes_nothing(self) -> None:
        merged = merged_live()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "ruleset.json", DECLARED)
            gh = FakeGh(get_sequence=[merged])
            rc, out, err = run_main(
                ["--repo", "VMAFx/.github", "--file", str(path)],
                gh,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(err, "")
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
            self.assertEqual(
                err,
                "ruleset list: unparseable JSON (JSONDecodeError): "
                "Expecting value: line 1 column 1 (char 0)\n",
            )
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
        gh = FakeGh(get_sequence=[snapshot, re_read])
        self.assert_apply_failure(gh, SNAPSHOT_REFUSAL, 0)

    def test_changed_snapshot_with_unchanged_history(self) -> None:
        fresh = {**LIVE, "enforcement": "disabled"}
        gh = FakeGh(get_sequence=[LIVE, fresh], history_sequence=[[97], [97]])
        self.assert_apply_failure(gh, f"{REFUSAL_LINE}\n{NO_NEW_VERSION}", 0)

    def test_live_change_in_top_level_field_writes_nothing(self) -> None:
        re_read = json.loads(json.dumps(LIVE))
        re_read["bypass_actors"] = []
        gh = FakeGh(get_sequence=[LIVE, re_read])
        self.assert_apply_failure(gh, SNAPSHOT_REFUSAL, 0)

    def test_readback_missing_live_only_rule_fails(self) -> None:
        live = json.loads(json.dumps(LIVE))
        live["rules"].append({"type": "creation"})
        readback = json.loads(json.dumps(live))
        readback["rules"] = [r for r in readback["rules"] if r["type"] != "creation"]
        gh = FakeGh(get_sequence=[live, live, readback])
        self.assert_apply_failure(
            gh,
            "rule copilot_code_review: missing after read-back\n"
            "rule creation: live-only rule from the snapshot missing after read-back\n"
            "ruleset history shows 1 new version (4101)",
            1,
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
        gh = FakeGh(get_sequence=[live, live, readback])
        self.assert_apply_failure(
            gh,
            "rule copilot_code_review: missing after read-back\n"
            "rule creation: live-only parameters changed after read-back\n"
            "ruleset history shows 1 new version (4101)",
            1,
        )

    def test_readback_lost_live_only_parameter_on_declared_rule_fails(self) -> None:
        readback = merged_live()
        pull_request = next(r for r in readback["rules"] if r["type"] == "pull_request")
        del pull_request["parameters"][
            "require_extra_approval_for_unattributed_changes"
        ]
        gh = FakeGh(get_sequence=[LIVE, LIVE, readback])
        self.assert_apply_failure(
            gh,
            "rule pull_request: live-only parameter "
            "require_extra_approval_for_unattributed_changes changed after read-back\n"
            "ruleset history shows 1 new version (4101)",
            1,
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
            self.assertEqual(err, WRITING)
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
    def test_invalid_utf8_stdout(self) -> None:
        cmd = ["gh", "api", "test"]
        result = subprocess.CompletedProcess(cmd, 0, b'{"name": "\xff"}', b"")
        with patch.object(subprocess, "run", return_value=result):
            self.assertEqual(apply_ruleset.run_gh(cmd[1:]), '{"name": "\ufffd"}')

    def test_invalid_utf8_stderr(self) -> None:
        cmd = ["gh", "api", "test"]
        result = subprocess.CompletedProcess(cmd, 1, b"", b"\xff boom")
        with (
            patch.object(subprocess, "run", return_value=result),
            self.assertRaises(apply_ruleset.GhError) as raised,
        ):
            apply_ruleset.run_gh(cmd[1:])
        self.assertEqual(
            str(raised.exception), f"command: {cmd!r}\nstderr: \ufffd boom"
        )

    def test_binary_stdin(self) -> None:
        cmd = ["gh", "api", "test"]
        result = subprocess.CompletedProcess(cmd, 0, b"", b"")
        with patch.object(subprocess, "run", return_value=result) as run:
            apply_ruleset.run_gh(cmd[1:], stdin="{}")
        self.assertEqual(run.call_args.kwargs["input"], b"{}")
        self.assertNotIn("text", run.call_args.kwargs)

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
