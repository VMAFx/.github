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
- You need the `gh` CLI authenticated with administration permission on the
  repository.
- Tests: `python3 -B -m unittest discover -s tests/ruleset -t .`