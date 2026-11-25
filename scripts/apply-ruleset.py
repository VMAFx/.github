#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2
"""Apply the declared branch ruleset in .github/rulesets/ to GitHub.

Operational detail lives in docs/rulesets.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

TOP_LEVEL_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors")
HISTORY_PAGE = 100
MAX_HISTORY_PAGES = 10
GH_JSON_ERRORS = (ValueError, RecursionError)


class GhError(Exception):
    """A GitHub CLI request failed."""


def run_gh(args: list[str], stdin: str | None = None) -> str:
    """Run ``gh`` with a bounded wait, replacing invalid UTF-8 in output with U+FFFD."""
    cmd = ["gh", *args]
    try:
        result = subprocess.run(
            cmd,
            input=stdin.encode("utf-8") if stdin is not None else None,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise GhError(f"command: {cmd!r}\n{exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise GhError(f"command: {cmd!r}\nstderr: {stderr.strip()}")
    return result.stdout.decode("utf-8", errors="replace")


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _rules_by_type(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {rule["type"]: rule for rule in rules}


def validate_declared(data: Any) -> list[str]:
    """Return validation error messages, or an empty list when valid."""
    if not isinstance(data, dict):
        return ["ruleset file must be a JSON object"]
    errors: list[str] = []
    for key in (*TOP_LEVEL_KEYS, "rules"):
        if key not in data:
            errors.append(f"ruleset file missing required key: {key}")
    return errors + _rule_shape_errors(data.get("rules"))


def _rule_shape_errors(rules: Any) -> list[str]:
    if not isinstance(rules, list):
        return ["rules must be a list"]
    errors: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{index}] must be an object")
            continue
        rule_type = rule.get("type")
        if not isinstance(rule_type, str):
            errors.append(f"rules[{index}] must have a string type")
    return errors


def load_declared(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def discover_repo(gh: Callable[..., str]) -> str:
    out = gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    repo = out.strip()
    if not repo:
        raise GhError("repo view returned an empty nameWithOwner")
    return repo


def _load_gh_json(raw: str, what: str) -> Any:
    try:
        return json.loads(raw)
    except GH_JSON_ERRORS as exc:
        detail = f"{what}: unparseable JSON ({type(exc).__name__}): {exc}"
        raise GhError(detail) from exc


def list_rulesets(gh: Callable[..., str], repo: str) -> list[dict[str, Any]]:
    path = f"repos/{repo}/rulesets?includes_parents=false&per_page=100"
    raw = gh(["api", path])
    data = _load_gh_json(raw, "ruleset list")
    if not isinstance(data, list):
        raise GhError(f"unexpected ruleset list payload type: {type(data).__name__}")
    return data


def fetch_ruleset(
    gh: Callable[..., str], repo: str, ruleset_id: int, *, readback: bool = False
) -> dict[str, Any]:
    raw = gh(["api", f"repos/{repo}/rulesets/{ruleset_id}"])
    data = _load_gh_json(raw, "read-back failed" if readback else "ruleset")
    if not isinstance(data, dict):
        if readback:
            raise GhError("malformed ruleset read-back: expected an object")
        raise GhError(f"unexpected ruleset payload type: {type(data).__name__}")
    if readback:
        errors = _rule_shape_errors(data.get("rules"))
        if errors:
            raise GhError(f"malformed ruleset read-back: {errors[0]}")
    return data


def fetch_history_ids(gh: Callable[..., str], repo: str, ruleset_id: int) -> set[int]:
    """Read complete history or fail when the page limit prevents verification."""
    path = f"repos/{repo}/rulesets/{ruleset_id}/history?per_page={HISTORY_PAGE}"
    ids: set[int] = set()
    for page in range(1, MAX_HISTORY_PAGES + 1):
        raw = gh(["api", f"{path}&page={page}"])
        data = _load_gh_json(raw, f"ruleset history page {page}")
        if not isinstance(data, list):
            raise GhError(
                f"unexpected ruleset history payload type: {type(data).__name__}"
            )
        for entry in data:
            version = entry.get("version_id") if isinstance(entry, dict) else None
            if not isinstance(version, int) or isinstance(version, bool):
                raise GhError("ruleset history entry without an integer version_id")
            ids.add(version)
        if len(data) < HISTORY_PAGE:
            return ids
    raise GhError(f"history longer than {MAX_HISTORY_PAGES} pages")


def _history_pointer(repo: str, ruleset_id: int) -> str:
    return (
        f"inspect each version with gh api "
        f"repos/{repo}/rulesets/{ruleset_id}/history/<version_id>, restore the "
        "intended state, then re-run"
    )


def find_ruleset_id(entries: list[dict[str, Any]], name: str) -> int | None:
    matches = [entry for entry in entries if entry.get("name") == name]
    if len(matches) != 1:
        return None
    ruleset_id = matches[0].get("id")
    if not isinstance(ruleset_id, int):
        return None
    return ruleset_id


def _merged_rule(
    live_rule: dict[str, Any], file_rule: dict[str, Any]
) -> dict[str, Any]:
    merged: dict[str, Any] = {"type": file_rule["type"]}
    live_params = live_rule.get("parameters")
    file_params = file_rule.get("parameters")
    if isinstance(live_params, dict) or isinstance(file_params, dict):
        live_map = live_params if isinstance(live_params, dict) else {}
        file_map = file_params if isinstance(file_params, dict) else {}
        if live_map or file_map:
            merged["parameters"] = {**live_map, **file_map}
    return merged


def merge_ruleset(live: dict[str, Any], declared: dict[str, Any]) -> dict[str, Any]:
    """Build the desired payload: file top-level fields plus merged rules."""
    declared_map = _rules_by_type(declared["rules"])
    live_map = _rules_by_type(live.get("rules", []))
    merged_rules: list[dict[str, Any]] = []
    for live_rule in live.get("rules", []):
        rule_type = live_rule.get("type")
        if not isinstance(rule_type, str):
            continue
        if rule_type in declared_map:
            merged_rules.append(_merged_rule(live_rule, declared_map[rule_type]))
        else:
            merged_rules.append(live_rule)
    present = {rule["type"] for rule in merged_rules}
    for file_rule in declared["rules"]:
        rule_type = file_rule["type"]
        if rule_type not in present and rule_type not in live_map:
            merged_rules.append(_merged_rule({}, file_rule))
        elif rule_type not in present:
            merged_rules.append(_merged_rule(live_map[rule_type], file_rule))
    desired: dict[str, Any] = {key: declared[key] for key in TOP_LEVEL_KEYS}
    desired["rules"] = merged_rules
    return desired


def _top_level_diffs(live: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in TOP_LEVEL_KEYS:
        old = live.get(key)
        new = desired.get(key)
        if old != new:
            lines.append(f"{key}: {_compact(old)} -> {_compact(new)}")
    return lines


def _rule_diffs(live: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    live_map = _rules_by_type(live.get("rules", []))
    desired_map = _rules_by_type(desired.get("rules", []))
    lines: list[str] = []
    for rule_type, desired_rule in desired_map.items():
        if rule_type not in live_map:
            lines.append(f"rule {rule_type}: added")
            continue
        live_rule = live_map[rule_type]
        live_params = live_rule.get("parameters", {})
        desired_params = desired_rule.get("parameters", {})
        if not isinstance(live_params, dict):
            live_params = {}
        if not isinstance(desired_params, dict):
            desired_params = {}
        for param in sorted(set(live_params) | set(desired_params)):
            old = live_params.get(param)
            new = desired_params.get(param)
            if old != new:
                lines.append(
                    f"rule {rule_type}: parameter {param}: {_compact(old)} -> {_compact(new)}"
                )
    return lines


def differences(live: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    """Describe top-level and per-rule changes between live and desired."""
    return _top_level_diffs(live, desired) + _rule_diffs(live, desired)


def _snapshot_view(ruleset: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {key: ruleset.get(key) for key in TOP_LEVEL_KEYS}
    view["rules"] = ruleset.get("rules", [])
    return view


def _rule_params(rule: dict[str, Any]) -> dict[str, Any]:
    params = rule.get("parameters", {})
    return params if isinstance(params, dict) else {}


def _live_only_readback_errors(
    readback_map: dict[str, dict[str, Any]],
    declared: dict[str, Any],
    live: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    declared_types = {rule["type"] for rule in declared.get("rules", [])}
    for rule in live.get("rules", []):
        rule_type = rule.get("type")
        if not isinstance(rule_type, str) or rule_type in declared_types:
            continue
        if rule_type not in readback_map:
            errors.append(
                f"rule {rule_type}: live-only rule from the snapshot missing after read-back"
            )
            continue
        if _rule_params(readback_map[rule_type]) != _rule_params(rule):
            errors.append(
                f"rule {rule_type}: live-only parameters changed after read-back"
            )
    return errors


def _live_only_param_errors(
    readback_map: dict[str, dict[str, Any]],
    declared: dict[str, Any],
    live: dict[str, Any],
) -> list[str]:
    """Report snapshot parameters the file omits on a declared rule that the write lost."""
    errors: list[str] = []
    live_map = _rules_by_type(live.get("rules", []))
    for rule in declared.get("rules", []):
        rule_type = rule["type"]
        if rule_type not in live_map or rule_type not in readback_map:
            continue
        file_params = _rule_params(rule)
        rb_params = _rule_params(readback_map[rule_type])
        for param, expected in _rule_params(live_map[rule_type]).items():
            if param not in file_params and rb_params.get(param) != expected:
                errors.append(
                    f"rule {rule_type}: live-only parameter {param} changed after read-back"
                )
    return errors


def readback_errors(
    readback: dict[str, Any], declared: dict[str, Any], live: dict[str, Any]
) -> list[str]:
    """Verify read-back matches declared fields, file rules, and live-only snapshot rules."""
    errors: list[str] = []
    for key in TOP_LEVEL_KEYS:
        if readback.get(key) != declared.get(key):
            errors.append(f"{key}: read-back does not match declared file")
    readback_map = _rules_by_type(readback.get("rules", []))
    for rule in declared.get("rules", []):
        rule_type = rule["type"]
        if rule_type not in readback_map:
            errors.append(f"rule {rule_type}: missing after read-back")
            continue
        file_params = _rule_params(rule)
        rb_params = _rule_params(readback_map[rule_type])
        for param, expected in file_params.items():
            if rb_params.get(param) != expected:
                errors.append(f"rule {rule_type}: parameter {param} read-back mismatch")
    errors.extend(_live_only_readback_errors(readback_map, declared, live))
    errors.extend(_live_only_param_errors(readback_map, declared, live))
    return errors


def _print_kept_live_rules(live: dict[str, Any], declared: dict[str, Any]) -> None:
    declared_types = {rule["type"] for rule in declared.get("rules", [])}
    for rule in live.get("rules", []):
        rule_type = rule.get("type")
        if isinstance(rule_type, str) and rule_type not in declared_types:
            print(f"kept live rule not in the file: {rule_type}")


def _put_ruleset(
    gh: Callable[..., str], repo: str, ruleset_id: int, payload: str
) -> None:
    gh(
        ["api", "-X", "PUT", f"repos/{repo}/rulesets/{ruleset_id}", "--input", "-"],
        payload,
    )


def _load_declared_or_report(path: Path) -> dict[str, Any] | None:
    try:
        declared = load_declared(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return None
    errors = validate_declared(declared)
    if errors:
        for message in errors:
            print(message, file=sys.stderr)
        return None
    return declared


def _locate_ruleset(gh: Callable[..., str], repo: str, name: str) -> int | None:
    entries = list_rulesets(gh, repo)
    ruleset_id = find_ruleset_id(entries, name)
    if ruleset_id is not None:
        return ruleset_id
    names = [entry.get("name") for entry in entries if entry.get("name") == name]
    if not names:
        print(
            f"no live ruleset named {name!r}; will not create one",
            file=sys.stderr,
        )
    else:
        print(
            f"more than one live ruleset named {name!r}; will not update",
            file=sys.stderr,
        )
    return None


def _exception_name(exc: BaseException) -> str:
    # Read the actual class name even if its metaclass overrides attribute access.
    return str.__str__(type.__dict__["__name__"].__get__(type(exc)))


def _describe(exc: BaseException) -> str:
    try:
        # A str subclass returned by __str__ could override __format__.
        return str.__str__(str(exc))
    except Exception as error:  # noqa: BLE001 - formatting can raise any Exception
        name = _exception_name(exc)
        try:
            return f"{name} (message unavailable: {type(error).__name__})"
        except Exception:  # noqa: BLE001 - keep the original exception's name
            return name


def _emit(stream: TextIO, text: str) -> bool:
    try:
        line = text + "\n"
        written = stream.write(line)
        stream.flush()
        return written == len(line)
    except Exception:  # noqa: BLE001 - the pre-PUT pointer survives a failed report
        return False


def _history_report(
    gh: Callable[..., str],
    repo: str,
    ruleset_id: int,
    before: set[int],
    *,
    after_write: bool,
) -> tuple[bool, str]:
    """Return whether exactly one version appeared and the diagnostic line."""
    reportable = Exception if after_write else GhError
    try:
        new = sorted(fetch_history_ids(gh, repo, ruleset_id) - before)
        if not new:
            return (
                False,
                "ruleset history shows no new version since the initial history read",
            )
        single = len(new) == 1
        versions = "version" if single else "versions"
        ids = ", ".join(map(str, new))
        return single, f"ruleset history shows {len(new)} new {versions} ({ids})"
    except reportable as exc:
        if issubclass(type(exc), GhError):
            try:
                cause = BaseException.__dict__["__cause__"].__get__(exc)
            except Exception:  # noqa: BLE001 - preserve the history diagnostic
                cause = None
            if not issubclass(type(cause), GH_JSON_ERRORS):
                return False, f"history unreadable: {_describe(exc)}"
        return False, f"history unreadable ({_exception_name(exc)}): {_describe(exc)}"


def _verify_write(
    gh: Callable[..., str],
    repo: str,
    ruleset_id: int,
    live: dict[str, Any],
    declared: dict[str, Any],
    before: set[int],
) -> int:
    # After PUT, failures must reach the history line and pointer. BaseException passes.
    try:
        readback = fetch_ruleset(gh, repo, ruleset_id, readback=True)
        errors = readback_errors(readback, declared, live)
    except GhError as exc:
        errors = [_describe(exc)]
    except Exception as exc:  # noqa: BLE001 - history still needs to be read
        errors = [f"read-back failed ({_exception_name(exc)}): {_describe(exc)}"]

    single, history = _history_report(gh, repo, ruleset_id, before, after_write=True)
    if single and not errors:
        message = f"read-back: {len(declared['rules'])} declared rules match"
        if _emit(sys.stdout, message):
            return 0
        errors = ["could not write read-back result to stdout"]
    pointer = _history_pointer(repo, ruleset_id)
    _emit(sys.stderr, "\n".join([*errors, history, pointer]))
    return 1


def _write_and_verify(
    gh: Callable[..., str],
    repo: str,
    ruleset_id: int,
    live: dict[str, Any],
    desired: dict[str, Any],
    declared: dict[str, Any],
) -> int:
    pointer = _history_pointer(repo, ruleset_id)
    try:
        before = fetch_history_ids(gh, repo, ruleset_id)
    except GhError as exc:
        print(f"history unreadable: {_describe(exc)}\n{pointer}", file=sys.stderr)
        return 1

    def report_failure(exc: Exception, *, after_write: bool) -> int:
        _, history = _history_report(
            gh, repo, ruleset_id, before, after_write=after_write
        )
        _emit(sys.stderr, f"{_describe(exc)}\n{history}\n{pointer}")
        return 1

    try:
        fresh = fetch_ruleset(gh, repo, ruleset_id)
        if _snapshot_view(fresh) != _snapshot_view(live):
            raise GhError(
                f"live ruleset {declared['name']} ({ruleset_id}) changed since it was "
                "read; nothing written; re-run to merge against the current state"
            )
    except GhError as exc:
        return report_failure(exc, after_write=False)

    payload = json.dumps(desired)
    print(
        f"writing ruleset {declared['name']} ({ruleset_id}); "
        f"version history: {pointer}",
        file=sys.stderr,
        flush=True,
    )
    try:
        _put_ruleset(gh, repo, ruleset_id, payload)
    except Exception as exc:  # noqa: BLE001 - the PUT may have committed
        return report_failure(exc, after_write=True)
    return _verify_write(gh, repo, ruleset_id, live, declared, before)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a declared GitHub ruleset JSON file."
    )
    parser.add_argument(
        "--file",
        default=".github/rulesets/main.json",
        help="Path to the declared ruleset JSON (default: .github/rulesets/main.json)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository as OWNER/NAME (default: current repo from gh repo view)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes; without this flag the script only reports differences",
    )
    return parser.parse_args(argv)


def main(argv: list[str], gh: Callable[..., str] = run_gh) -> int:
    args = parse_args(argv)
    path = Path(args.file)
    declared = _load_declared_or_report(path)
    if declared is None:
        return 1
    try:
        repo = args.repo or discover_repo(gh)
        ruleset_id = _locate_ruleset(gh, repo, declared["name"])
        if ruleset_id is None:
            return 1
        live = fetch_ruleset(gh, repo, ruleset_id)
        _print_kept_live_rules(live, declared)
        desired = merge_ruleset(live, declared)
        diff_lines = differences(live, desired)
        if not diff_lines:
            print(
                f"live ruleset {declared['name']} ({ruleset_id}) already matches {path}"
            )
            return 0
        for line in diff_lines:
            print(line)
        if not args.apply:
            print("dry run: rerun with --apply to write these changes")
            return 0
        return _write_and_verify(gh, repo, ruleset_id, live, desired, declared)
    except GhError as exc:
        _emit(sys.stderr, _describe(exc))
        return 1


def _cli() -> int:
    try:
        status = main(sys.argv[1:])
    finally:
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            # CPython retries this flush at shutdown and can replace the exit status.
            with open(os.devnull, "w") as sink:
                os.dup2(sink.fileno(), 1)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(_cli())
