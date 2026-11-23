#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2
"""Apply the declared branch ruleset in .github/rulesets/ to GitHub.

Operational detail lives in docs/rulesets.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOP_LEVEL_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors")
HISTORY_PAGE = 100
MAX_WRITE_ROUNDS = 3


class GhError(Exception):
    """``gh`` exited non-zero."""


def run_gh(args: list[str], stdin: str | None = None) -> str:
    """Run ``gh`` with a bounded wait and return stdout."""
    cmd = ["gh", *args]
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(f"command: {cmd!r}\nstderr: {result.stderr.strip()}")
    return result.stdout


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
    rules = data.get("rules")
    if not isinstance(rules, list):
        errors.append("rules must be a list")
        return errors
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


def list_rulesets(gh: Callable[..., str], repo: str) -> list[dict[str, Any]]:
    path = f"repos/{repo}/rulesets?includes_parents=false&per_page=100"
    raw = gh(["api", path])
    data = json.loads(raw)
    if not isinstance(data, list):
        raise GhError(f"unexpected ruleset list payload type: {type(data).__name__}")
    return data


def fetch_ruleset(gh: Callable[..., str], repo: str, ruleset_id: int) -> dict[str, Any]:
    raw = gh(["api", f"repos/{repo}/rulesets/{ruleset_id}"])
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise GhError(f"unexpected ruleset payload type: {type(data).__name__}")
    return data


def fetch_history_ids(gh: Callable[..., str], repo: str, ruleset_id: int) -> set[int]:
    """Return the version ids on the first page of the ruleset history."""
    path = f"repos/{repo}/rulesets/{ruleset_id}/history?per_page={HISTORY_PAGE}"
    data = json.loads(gh(["api", path]))
    if not isinstance(data, list):
        raise GhError(f"unexpected ruleset history payload type: {type(data).__name__}")
    ids: set[int] = set()
    for entry in data:
        version = entry.get("version_id") if isinstance(entry, dict) else None
        if not isinstance(version, int) or isinstance(version, bool):
            raise GhError("ruleset history entry without an integer version_id")
        ids.add(version)
    return ids


def _history_pointer(repo: str, ruleset_id: int) -> str:
    return (
        f"inspect each version with gh api "
        f"repos/{repo}/rulesets/{ruleset_id}/history/<version_id>, restore the "
        "intended state, then re-run"
    )


def concurrent_write_errors(
    repo: str, ruleset_id: int, before: set[int], after: set[int]
) -> list[str]:
    """Return errors unless the write added exactly one history version."""
    new = sorted(after - before)
    if len(new) == 1:
        return []
    if new:
        found = ", ".join(str(version) for version in new)
        reason = (
            f"ruleset history shows {len(new)} new versions ({found}) where this "
            "write adds one: another client changed the ruleset during the apply"
        )
    else:
        reason = "ruleset history shows no new version after the write"
    return [f"{reason}; {_history_pointer(repo, ruleset_id)}"]


def fetch_version_state(
    gh: Callable[..., str], repo: str, ruleset_id: int, version_id: int
) -> dict[str, Any]:
    raw = gh(["api", f"repos/{repo}/rulesets/{ruleset_id}/history/{version_id}"])
    data = json.loads(raw)
    state = data.get("state") if isinstance(data, dict) else None
    if not isinstance(state, dict):
        raise GhError(f"ruleset history version {version_id} has no state object")
    return state


def _matches_payload(state: dict[str, Any], payload: dict[str, Any]) -> bool:
    for key in TOP_LEVEL_KEYS:
        if state.get(key) != payload.get(key):
            return False
    state_rules = state.get("rules", [])
    payload_rules = payload.get("rules", [])
    state_map = {t: _rule_params(r) for t, r in _rules_by_type(state_rules).items()}
    payload_map = {t: _rule_params(r) for t, r in _rules_by_type(payload_rules).items()}
    return state_map == payload_map


def _other_version(
    gh: Callable[..., str],
    repo: str,
    ruleset_id: int,
    new_ids: list[int],
    payload: dict[str, Any],
) -> tuple[tuple[int, dict[str, Any]] | None, list[str]]:
    pointer = _history_pointer(repo, ruleset_id)
    own: list[int] = []
    other: list[tuple[int, dict[str, Any]]] = []
    for version_id in new_ids:
        state = fetch_version_state(gh, repo, ruleset_id, version_id)
        if _matches_payload(state, payload):
            own.append(version_id)
        else:
            other.append((version_id, state))
    if not own:
        found = ", ".join(str(version) for version in new_ids)
        return (
            None,
            [
                f"cannot find this write among the new ruleset versions ({found}); "
                f"{pointer}"
            ],
        )
    if len(other) > 1:
        found = ", ".join(str(version) for version, _ in other)
        return (
            None,
            [
                f"{len(other)} new ruleset versions from other clients ({found}) "
                f"differ from this write; {pointer}"
            ],
        )
    if not other:
        return (None, [])
    version_id, state = other[0]
    return ((version_id, state), [])


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
    gh: Callable[..., str], repo: str, ruleset_id: int, desired: dict[str, Any]
) -> None:
    payload = json.dumps(desired)
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


def _finish_readback(
    readback: dict[str, Any], declared: dict[str, Any], base: dict[str, Any]
) -> int:
    errors = readback_errors(readback, declared, base)
    if errors:
        for message in errors:
            print(message, file=sys.stderr)
        return 1
    rule_count = len(declared.get("rules", []))
    print(f"read-back: {rule_count} declared rules match")
    return 0


def _write_round(
    gh: Callable[..., str],
    repo: str,
    ruleset_id: int,
    declared: dict[str, Any],
    base: dict[str, Any],
    payload: dict[str, Any],
    before: set[int],
    round_num: int,
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None, set[int] | None]:
    _put_ruleset(gh, repo, ruleset_id, payload)
    readback = fetch_ruleset(gh, repo, ruleset_id)
    after = fetch_history_ids(gh, repo, ruleset_id)
    new = sorted(after - before)
    if len(new) == 1:
        return (_finish_readback(readback, declared, base), None, None, None)
    if not new:
        for message in concurrent_write_errors(repo, ruleset_id, before, after):
            print(message, file=sys.stderr)
        return (1, None, None, None)
    other, errors = _other_version(gh, repo, ruleset_id, new, payload)
    if errors:
        for message in errors:
            print(message, file=sys.stderr)
        return (1, None, None, None)
    if other is None:
        return (_finish_readback(readback, declared, base), None, None, None)
    version_id, state = other
    print(
        f"another client wrote ruleset version {version_id} during the apply; "
        "merged its state with the declared file and writing again "
        f"(write {round_num + 1} of {MAX_WRITE_ROUNDS})"
    )
    return (2, state, merge_ruleset(state, declared), after)


def _write_and_verify(
    gh: Callable[..., str],
    repo: str,
    ruleset_id: int,
    live: dict[str, Any],
    desired: dict[str, Any],
    declared: dict[str, Any],
) -> int:
    before = fetch_history_ids(gh, repo, ruleset_id)
    fresh = fetch_ruleset(gh, repo, ruleset_id)
    if _snapshot_view(fresh) != _snapshot_view(live):
        print(
            f"live ruleset {declared['name']} ({ruleset_id}) changed since it was read; "
            "nothing written; re-run to merge against the current state",
            file=sys.stderr,
        )
        return 1
    base = live
    payload = desired
    for round_num in range(MAX_WRITE_ROUNDS):
        code, retry_base, retry_payload, retry_before = _write_round(
            gh, repo, ruleset_id, declared, base, payload, before, round_num
        )
        if code == 2:
            base = retry_base or base
            payload = retry_payload or payload
            before = retry_before or before
            continue
        return code
    pointer = _history_pointer(repo, ruleset_id)
    print(
        f"ruleset history shows writes by other clients during each of "
        f"{MAX_WRITE_ROUNDS} writes; {pointer}",
        file=sys.stderr,
    )
    return 1


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
    except (GhError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
