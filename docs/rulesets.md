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

An apply that changes the ruleset sends one `PUT`. Before writing, the script
reads the history IDs and fetches the ruleset again. If the fields used for the
merge have changed, the script exits with status 1 before sending the update.
Another client can still edit the ruleset between that last read and the
update because the [ruleset update endpoint][update] has no conditional write.

After a successful `PUT` response, the script reads the ruleset and its history
again. A `PUT` error skips the ruleset read-back but still triggers the history
read because GitHub may have recorded the update. The script exits
with status 0 only when exactly one new version appears and the read-back
matches the declared fields and rules, including the live-only rules and
parameters from the original snapshot. A single new ID does not identify its
author.

Every status 1 exit after the initial history read reports the failure, then
lists all new version IDs in ascending order, reports that none appeared, or
gives the history error. Each history read stops at 10 pages of 100 entries.
A full tenth page makes the history unreadable.
Inspect each reported version with the following command, restore the
intended state from the ruleset history, then re-run the apply.

```bash
gh api repos/{owner}/{repo}/rulesets/{ruleset_id}/history/{version_id}
```

[update]: https://docs.github.com/en/rest/repos/rules#update-a-repository-ruleset

## Reference

- The script finds an existing ruleset by the `name` field in the JSON file.
  It never creates or deletes a ruleset.
- Rules and rule parameters that exist only on the live GitHub ruleset are
  kept. The apply step adds or updates what the file declares without
  weakening stricter live settings that the file omits.
- You need the `gh` CLI authenticated with administration permission on the
  repository.
- Tests: `python3 -B -m unittest discover -s tests/ruleset -t .`
