<!-- SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me> -->
<!-- SPDX-License-Identifier: EUPL-1.2 -->

# Branch ruleset

The file `.github/rulesets/main.json` is the repository's declared branch
ruleset for GitHub. Merging a pull request that changes that file does not,
by itself, change what GitHub enforces on the default branch.

After such a change lands on the default branch, a repository administrator
should apply it from a checkout of that branch:

```bash
python3 scripts/apply-ruleset.py
```

That command is a dry run: it prints what would change and exits without
writing anything. To push the declared ruleset to GitHub:

```bash
python3 scripts/apply-ruleset.py --apply
```

The script reads the ruleset back after a write and exits with status 1 when
any value from the declared file did not take effect.

## Reference

- The script finds an existing ruleset by the `name` field in the JSON file.
  It never creates or deletes a ruleset.
- Rules and rule parameters that exist only on the live GitHub ruleset are
  kept. The apply step adds or updates what the file declares without
  weakening stricter live settings that the file omits.
- Before writing, the script reads the ruleset again and exits with status 1
  without writing when the live ruleset changed since the first read. After a
  write, it also fails when a live-only rule, or a live-only parameter of any
  rule, did not survive the read-back. The GitHub REST API does not support
  conditional `PUT` requests (GitHub Docs, "Best practices for using the REST
  API", section "Use conditional requests"), so a write by another client, the
  GitHub web UI included, between that second read and the write cannot be
  prevented. The script detects it instead and restores what the overlapping
  write would lose: it reads the ruleset history
  (`GET /repos/{owner}/{repo}/rulesets/{ruleset_id}/history`) before the second
  read and again after the read-back. When more than one new version appeared,
  it reads each new version's state
  (`GET /repos/{owner}/{repo}/rulesets/{ruleset_id}/history/{version_id}`),
  and attributes its write only if exactly one state matches its payload.
  If one other version appeared on the first write, the script merges that
  version's state with the declared file and writes once more. This preserves
  rules the other client added and restores declared rules it removed.
  A second overlap stops recovery because another merge could drop a rule
  the first writer added (see `test_second_foreign_write_stops_recovery`).
  Recovery also stops if no version appeared, if zero or multiple versions
  match the payload, or if multiple other versions differ from it. On failure
  the script exits with status 1. It lists the known foreign versions and any
  unattributed candidates from both writes, with the history endpoint for
  manual restoration. A write by another client after
  the final read-back is not checked; the next run reconciles it.
- You need the `gh` CLI authenticated with administration permission on the
  repository.
- Tests: `python3 -B -m unittest discover -s tests/ruleset -t .`
