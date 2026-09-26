---
name: codebase-audit
description: "Codebase audit / codereview — a read-only whole-codebase review that records findings as entries in a persistent, idempotent ledger (stable IDs, survives re-runs) under /home/user/codereview/PROJECT_NAME/ledger.md. Use whenever the user asks for a \"codereview,\" \"code audit,\" \"codebase audit,\" or \"full review.\" Distinct from requesting-code-review, which reviews one diff/PR. Also triggers automatically at the end of a dev-sprint run once all phases are complete. Never edits code."
---

# Codebase Audit

A read-only, whole-codebase review that produces a persistent, append-and-merge findings ledger rather than a disposable report. The point of persistence: your approvals survive across runs, `nightly-support` can tell "still open" from "already fixed," and nothing gets double-ticketed.

## Where things live

- All ledgers live under one shared root: `/home/user/codereview/<project-name>/ledger.md` — one ledger per project, named to match the project dir under `/home/user/`.
- Read `references/ledger-schema.md` before creating or updating a ledger — it has the exact per-entry field schema and merge rules. Don't freewheel the schema; do freewheel the `category`/`severity` labels you assign within it.

## When to run

- User explicitly asks for a codebase audit / codereview of a project.
- Automatically, one-shot, when a `dev-sprint` run's gatelog reaches "All phases complete" (see dev-sprint's "When all phases are complete" step) — this closes the loop for ticket-originated work by letting the corresponding ledger entries move toward `resolved` on the next `nightly-support` pass.
- On a recurring cron cadence the user set up for a project (see "Cron / recurring usage" below).

## Step 1: Identify the project and load prior state

0. **Check the dev-dashboard ledger first.** Read
   `dev-sprint/references/dev-dashboard-ledger.md`. It is the control panel the
   user steers the loop from, and this skill is a **reader** of it: it decides
   which projects get audited, and when it provisions an audit cron it
   provisions **its own** job, named `<skill>-<project>-auto-<uid>`. The
   dashboard never creates a cron. If a project is absent from the ledger, or
   `audit.enabled` is false, that is the user's decision — do not audit it
   anyway. If it is listed and enabled but no job exists yet, this run is the one
   that provisions it (see "Cron / recurring usage" below).
1. Resolve the target project dir the same way `dev-sprint` does (given path, or a local dir matching the name/subject). Project directories are under `/home/user/projects/<name>/`.
2. Check `/home/user/codereview/<project-name>/ledger.md`. If it exists, read it in full — every existing entry, its `status`, and its `approved` flag. This run is a **merge**, not a fresh write.
3. If it doesn't exist, this is the first audit for this project — you'll create it fresh (still following the same schema).

**Prefer the parser over your own eyes.** These ledgers are hand-formatted YAML in
markdown and they drift — the first real ledger here had a field the schema did not
define, on all 53 entries. When this repo's `tools/` is available:

```bash
python3 tools/ledger.py validate /home/user/codereview/<project>/ledger.md
python3 tools/ledger.py stats    /home/user/codereview/<project>/ledger.md
python3 tools/ledger.py list     /home/user/codereview/<project>/ledger.md
```

`validate` checks field presence, id shape and uniqueness, legal status values, severity
and date ordering, and reports each problem with its entry id and line number. Run it
before you trust a ledger's contents, and again after you write to it. `next-id` gives
the next unused id (never reusing one from a resolved entry); `stale-assigned` finds
entries a crashed `nightly-support` run stranded in `assigned` — re-examine those rather
than treating them as still-open work.

## Step 2: Check for in-flight dev-sprint work (avoid overlap)

Before scanning, check whether this project has an active `dev-sprint` (a `plan.md`/`gatelog.md` with phases not yet all done). If so:
- Don't list a finding as fresh if it clearly overlaps with a phase already in progress in `plan.md`/`gatelog.md` — instead note the overlap against that entry (or skip creating a new one) so the user isn't asked to approve something already mid-fix.

## Step 3: Scan

Full codebase-wide by default. If the user gives an explicit scope (a subdirectory, or "just changed files" via `git diff`), narrow to that instead — full-repo scans are expensive and shouldn't be the only option.

Don't do this as one agent holding the whole codebase in its head. Use `delegation`/`a2a` to spawn parallel investigator agents — split either by area (one per module/directory) or by concern (one focused on bugs, one on security risks, one on code smells/pitfalls/gaps), whichever split makes more sense for the project's size and shape. Lean on:
- `codebase-inspection` for the actual review passes
- `context_engine` for understanding large or unfamiliar codebases
- `session_search` to check whether prior sessions already surfaced something relevant

This is strictly read-only. No edits, no fixes — flag it and move on. Fixing is `nightly-support` → `dev-sprint`'s job, once the user approves.

## Step 4: Merge findings into the ledger

For each candidate finding from the scan:
- **Matches an existing entry** (same location + same underlying issue): update its `last_seen` date. Don't create a duplicate. If its description has meaningfully changed, note that but keep the same stable ID.
- **New finding, no match:** append a new entry with a new stable ID (`CR-<project>-NNNN`, next unused number for this project), `status: new`, `approved: false`, `first_seen`/`last_seen` both set to today.
- **Existing entry no longer found this run:** don't delete it — mark `status: resolved` (unless it's already `ticketed`/`assigned`, in which case leave the ticket-driven flow in `nightly-support` to close it out) and add a one-line note that it wasn't observed on this pass.

Every entry carries a `covered_by_test` field saying what tests already cover the
behaviour and — more usefully — what they do **not** cover. Fill it in from reading the
tests, not from assumption; "no test exercises this" is usually the finding that most needs
writing, and it is what tells whoever picks up the ticket whether they are writing the
first test or extending one.

**Always update the `Last run:` date in the ledger header**, even on a run that found
nothing new. It is the audit's idempotency marker: `dev-sprint`'s completion step reads it
to decide whether the completion audit has already run, and a stale date makes a recurring
cron re-audit a finished project on every invocation.

Exact field-by-field schema, YAML shape, and worked examples are in
`references/ledger-schema.md` — use it verbatim, don't improvise field names.

## Step 5: Present

Present the ledger's current state (or a diff-style summary of what changed this run: N new, N still-open, N auto-resolved) to the user. The ledger file itself is the source of truth — don't also generate a separate one-off report file per run.

## Cron / recurring usage

A project can have a recurring codebase-audit cron set up two ways:
- The user explicitly asks for one (typically offered by `dev-sprint` when a project finishes in an interactive session — default interval 10 hours if the user doesn't specify).
- `nightly-support` triggers a one-shot run to close out resolved ledger entries after a ticket-originated `dev-sprint` finishes.

Each cron call runs Steps 1–5 above exactly as an interactive invocation would — this skill behaves identically whether triggered by a human or a schedule.

**When you provision, four things are not optional:**

1. The name is `<skill>-<project>-auto-<uid>` with a real `uuid4().hex[:8]`
   suffix. The `-auto-` infix is what marks the job as the loop's; without it
   the ownership check excludes it, so the job you just created would be one
   the system is forbidden to touch.
2. The name shape alone is **necessary but not sufficient** — a job is ours only
   if its `created_by` is `autonomous` as well. A user can name a job like ours
   by accident, which is why the check is two facts.
3. Filter to owned jobs before acting on any. Never "the first codebase-audit
   job" or "the job for this project" — a user-created job can share both the
   skill and the project name. `ownership.owned_jobs()` does the filtering.
4. Write the **real** name and the job's `job_id` back into the ledger, replacing
   the `-auto-00000000` placeholder the dashboard wrote. A job that exists but
   is not in the ledger is invisible to the next run.

```bash
hermes cron create "every 10 hours" "<the audit prompt>" \
    --name "codebase-audit-<project>-auto-<uid>" \
    --workdir "/home/user/projects/<project>" \
    --skill codebase-audit
```

Read `dev-sprint/references/dev-dashboard-ledger.md` for the full tool surface.

**Delete by `job_id`, and only after `ownership.assert_solvable()` confirms the
match is unambiguous and ours.** A self-destructing job deletes only its own
id — a job that was replaced under it must never be removed by name collision.

## Logging to the daily report

At the end of every run, append a short entry to today's daily report file (see the `daily-weekly-report` skill) — e.g. "codebase-audit: project X, 3 new findings, 2 auto-resolved, 5 still open awaiting approval."

## Agent delegation and the wider skill/tool pool

Read `references/agents-and-tools.md` before scanning — it's the canonical, up-to-date mapping of subtask → agent role → skills/tools for this entire skill family (dev-sprint, codebase-audit, nightly-support, daily-weekly-report), and includes the full expanded pool (`clarify`, `computer_use`, `github`, `simplify-code`, `spike`, `architecture-diagram`, and the rest). If dev-sprint's local copy of this reference ever disagrees with this one, treat this one as canonical.

## What this skill never does

- Never edits, fixes, or refactors code — read-only, always.
- Never flips the `approved` flag itself — that's the user's call, by hand, in the ledger file.
- Never writes a ticket or spec — that's `nightly-support`, and only for entries the user has already approved.
