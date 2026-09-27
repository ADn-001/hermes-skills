# Git and GitHub — the contract for sprint work

A sprint produces work. This file is what makes that work **land somewhere
durable** instead of dying with the cron that produced it.

Three moments matter, and only the third is optional:

| Moment | What happens | If it fails |
|---|---|---|
| **Before a phase** | working tree clean, branch checked against main for conflicts | stop and report; do not start the phase |
| **End of a phase** | commit → push → open/update PR → record the URL in the gatelog | do not mark the phase done |
| **Self-destruct (final)** | **all of the above, for the last phase** → then the cron deletes itself | **the self-destruct aborts** |

That last row is the whole reason this file exists. See "The self-destruct
rule" below.

---

## The self-destruct rule

When a sprint hits 2 consecutive no-op runs with every phase complete, the cron
deletes itself. That is the design — the job has served its purpose.

**The danger is the order of operations.** A cron that deletes itself while
holding uncommitted or unpushed work is a data-loss bug, and it is silent: the
job is gone, the work is gone, and the next session finds an empty phase marked
done. So the sequence is strictly ordered, and **the delete is last and
conditional**:

```
all phases complete
  →  no-op run 2 reached
  →  FINAL SYNC:  git add -A → commit → push → PR open/update
       └─ if ANY step fails → STOP. Do not write the marker.
                            Do not provision the audit.
                            Do NOT delete the cron.
                            Report the failure and leave the job alive,
                            so the next run retries.
  →  write the marker (generation fingerprint)
  →  provision the audit cron
  →  delete this cron
```

A failed push means the work exists only on this machine. Keeping a cron alive
to retry costs one scheduled no-op run. Deleting it costs the sprint. That is
not a close call.

---

## Before a phase starts

Do this **before writing any code**. Finding a conflict here is cheap; finding
it after a phase of work is expensive.

```bash
git fetch origin
git status --porcelain          # must be empty
git rev-parse --abbrev-ref HEAD # must NOT be main
```

**The working tree must be clean.** If it is not, something is uncommitted from
a previous run. Do not sweep it into this phase's commit and do not discard it —
report what is dirty and stop. A dirty tree at the start of a phase means an
earlier phase lied about finishing, and that is worth surfacing.

**Never work on `main`.** If the current branch is `main`, create a sprint
branch first:

```bash
git checkout -b dev-sprint/<project>-<phase-number>
```

**Check for conflicts against main before you start.** A branch that has fallen
behind will produce a merge conflict at PR time — possibly inside a file this
phase rewrote. Rebase onto main now, while there is nothing to lose:

```bash
git rebase origin/main || git merge origin/main
```

If that produces a conflict, resolve it **now**, run the tests, and only then
begin the phase. Do not carry a known conflict into new work.

**A project with no git at all** is a fresh-project case, not a conflict — see
"New projects" below.

---

## End of a phase

Only after the Test/Debug Sprint is **all green** (see the main SKILL.md).

```bash
git add -A
git commit -m "dev-sprint <project>: phase <N> — <phase name>

<one line on what the phase did and what proves it done>

Gate: <the e2e criteria from plan.md, and that they pass>"

git push -u origin <branch>
```

Then open the PR — or update it, because a sprint has exactly one branch per
project and one PR for the whole sprint:

```bash
# First phase of the sprint: open the PR.
gh pr create --base main --head <branch> \
  --title "dev-sprint <project>" \
  --body "<summary of the plan>"

# Every phase after that: the branch already has a PR, so just add a note.
gh pr comment <pr-number> --body "Phase <N> complete: <what it did>. Gate: <criteria>."
```

**Record the PR URL in the gatelog**, in that phase's findings section. The next
session has no memory beyond these files, and a PR number written nowhere is a
PR that gets duplicated.

```markdown
### Findings
...
- **PR:** https://github.com/<owner>/<repo>/pull/12 (phase 1 of 5; updated each phase)
```

Then mark the phase done. The order matters: **PR first, gatelog second.** A
gatelog that says "done" with no PR means the work exists only on this disk.

**The user merges.** This skill never merges to `main` and never pushes to it
directly. A PR that the user has not approved is exactly what a PR is for.

---

## New projects (no git, no remote)

When a sprint creates a new project directory, it must be a real repository from
the start — a sprint that produces an unversioned directory cannot be reviewed,
rolled back, or handed over.

```bash
cd <new-project-dir>
git init -b main
# write a .gitignore FIRST — a first commit full of __pycache__ and secrets
# is a commit you cannot easily unpick
git add -A
git commit -m "Initial commit: <project name>"
gh repo create <owner>/<name> --private --source=. --remote=origin --push
```

**Default to `--private`.** A new project is unpublished work; making it public
is a deliberate decision the user makes, not a default.

Then the normal flow applies: create the sprint branch and work there.

**If `gh` is not authenticated**, do not fake it and do not skip straight to
local commits — that recreates the problem this file exists to prevent. Report
it: the work is committed locally and pushed nowhere, and the user needs to
authenticate or create the remote. Record that in the gatelog so the next
session does not assume the push already happened.

---

## Rules that are not negotiable

- **Never `git push` to `main`.** Branches and PRs only. The user merges.
- **Never `git commit -a` with an unexamined diff.** `git add -A` then read
  `git diff --staged --stat` — a phase that accidentally swept in a `.env` or a
  database file is not caught by the test suite.
- **Never force-push a shared branch** (`--force`) without asking. If a rebase
  went wrong, `--force-with-lease` is the safe form, and even then: ask first if
  anyone else could have pushed to it.
- **Never amend or rebase a commit that is already pushed to a branch someone
  else may have pulled.** The sprint branch is shared with the user via the PR.
- **Do not commit `state.json`, tokens, or anything in `.gitignore`.** In
  particular, `.dashboard-token` is a credential and must never be pushed.
- **A failed push is never a reason to skip the PR step.** Report and stop.

---

## Working with an existing branch that already has commits

A sprint may resume onto a branch that already has work on it (a previous
session, or a branch the user started). That is normal:

- `git log origin/main..HEAD` shows what this sprint has accumulated.
- If a PR already exists for the branch, **update it** — do not open a second
  one. `gh pr list --head <branch> --state open` tells you.
- Do not rebase a branch that has an open PR with review comments on it without
  reading them first.

---

## What to put in the PR body

The user reads this to decide whether to merge. Give them what they need to
decide without re-running anything:

```markdown
## dev-sprint: <project>

<one paragraph: what this sprint is for>

### Phases
- [x] 1 — <name>  (PR comment, date)
- [x] 2 — <name>  (PR comment, date)
- [ ] 3 — <name>  ← in progress

### Gate for each phase
Phase N is done when: <the e2e criteria from plan.md>.
All phases' suites are run together; see the commit messages for the
per-phase gate evidence.

### Not in this PR
<anything deliberately left out, and why>
```

The "Not in this PR" section is not filler. It is where the user looks first to
find out what they are *not* getting.
