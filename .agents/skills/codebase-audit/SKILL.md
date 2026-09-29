---
name: codebase-audit
description: "Codebase audit / codereview — a read-only whole-codebase review that records findings as entries in a persistent, idempotent ledger (stable IDs, survives re-runs), one ledger per project under a shared codereview root. Use whenever the user asks for a \"codereview,\" \"code audit,\" \"codebase audit,\" or \"full review.\" Distinct from requesting-code-review, which reviews one diff/PR. Also triggers automatically at the end of a dev-sprint run once all phases are complete. Never edits code."
---

# Codebase Audit

A read-only, whole-codebase review that produces a persistent, append-and-merge findings ledger rather than a disposable report. The point of persistence: your approvals survive across runs, `nightly-support` can tell "still open" from "already fixed," and nothing gets double-ticketed.

## Where things live

Three paths, resolved once at the top of a session. They are variables rather
than literals because this repository is shared: an absolute path written into
a skill resolves on exactly one machine, and fails *silently* — a command
pointed at a directory that does not exist does not raise, it writes a ledger
nobody reads.

- **`$CODE_REVIEW`** — the shared findings root, holding one
  `<project-name>/ledger.md` per project. A **sibling** of `$PROJECTS`, not
  inside it. Find it with `find ~ -maxdepth 3 -name 'ledger.md' -path '*codereview*'`.
- **`$PROJECTS`** — the directory that *contains* project checkouts. Find it
  with `find ~ -maxdepth 3 -type d -name dev-dashboard`.
- **`$DASHBOARD`** — the dev-dashboard checkout, needed to read its ledger.

So a ledger is `$CODE_REVIEW/<project-name>/ledger.md`, and `<project-name>` is
the same string as the checkout directory under `$PROJECTS`.

- **Resolve `<project-name>` from the dashboard ledger, not by guessing.** The authoritative location of each project is the `"path"` field in `$DASHBOARD/state.json`. Read it with the library (`state.load(...)`), never by hand. Note that project names are real directory names and may contain uppercase (e.g. `Nanites-harness`); the ledger name must match the project name exactly, and the codereview subdirectory is the same name. Do not assume a project sits directly under the home directory — that was an older layout, and the audit root is the one directory that did **not** move with it.
- Read `references/ledger-schema.md` before creating or updating a ledger — it has the exact per-entry field schema and merge rules. Don't freewheel the schema; do freewheel the `category`/`severity` labels you assign within it.

## When to run

- User explicitly asks for a codebase audit / codereview of a project.
- Automatically, one-shot, when a `dev-sprint` run's gatelog reaches "All phases complete" (see dev-sprint's "When all phases are complete" step) — this closes the loop for ticket-originated work by letting the corresponding ledger entries move toward `resolved` on the next `nightly-support` pass.
- On a queued task: the project's audit toggle is on in the dev-dashboard
  ledger and the interval is due, so the dashboard enqueued one and the manager
  started a session for it (see "Scheduling" below). You do not arrange the
  trigger; the dashboard does.

## Step 1: Identify the project and load prior state

0. **Check the dev-dashboard ledger first.** Read
   `dev-sprint/references/dev-dashboard-ledger.md`. It is the control panel the
   user steers the loop from, and this skill is a **reader** of it: it decides
   which projects get audited and when one is due. **It also owns every
   scheduling decision**: it enqueues a task when the interval is due, and it
   starts this session. If a project is absent from the ledger, or
   `audit.enabled` is false, that is the user's decision — do not audit it
   anyway. If it is enabled but nothing has run yet, that means nothing is due,
   not that this run should arrange a schedule (see "Scheduling" below).
1. Resolve the target project dir the same way `dev-sprint` does (given path, or a local dir matching the name/subject). Project directories are under `$PROJECTS/<name>/`.
2. Check `$CODE_REVIEW/<project-name>/ledger.md`. If it exists, read it in full — every existing entry, its `status`, and its `approved` flag. This run is a **merge**, not a fresh write.
3. If it doesn't exist, this is the first audit for this project — you'll create it fresh (still following the same schema).

**Prefer the parser over your own eyes.** These ledgers are hand-formatted YAML in
markdown and they drift — the first real ledger here had a field the schema did not
define, on all 53 entries. When this repo's `tools/` is available:

```bash
python3 tools/ledger.py validate $CODE_REVIEW/<project>/ledger.md
python3 tools/ledger.py stats    $CODE_REVIEW/<project>/ledger.md
python3 tools/ledger.py list     $CODE_REVIEW/<project>/ledger.md
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

## Scheduling: this skill never provisions anything

**There is no per-project audit cron. There is no audit cron of any kind.** The
model that used to document one — `<skill>-<project>-auto-<uid>`, an audit job
per project, provisioned by this skill and recorded in the ledger — was removed
in Phase 19 and it must not come back.

An audit now happens because a **queue task** exists for it, and the task
exists because the project's audit toggle is on in the dev-dashboard ledger. The
dashboard's reconciler enqueues when the interval is due; the manager's tick
starts a session; this skill runs. Every scheduling decision belongs to the
dashboard, and this skill is a *worker* that happens to be good at audits.

**So: do not create, edit, pause, resume or delete a cron job.** Not for a
project, not for a one-shot, not because the user says "set up a recurring
audit". If the user wants an audit scheduled, the answer is the audit toggle in
the dashboard — say so, and do the audit now if they want it now.

This is not a style preference. The per-project cron model was the specific
thing that had to be dismantled: it meant N projects meant N crons racing for
one machine, and it meant a whole second scheduling system living alongside a
queue, a claim file and a busy check that already existed. On 2026-09-28 an
implementer read a table of cron names in the manager, concluded the system
provisioned one audit cron per project, and wrote it. The table was the fossil;
this file was the instruction to rebuild it.

Each run executes Steps 1–5 above exactly as an interactive invocation would —
this skill behaves identically whether a person asked for it or a queued task
started it. **The work is the same; only the trigger differs, and the trigger is
never yours to arrange.**

## Logging to the daily report

At the end of every run, append a short entry to today's daily report file (see the `daily-weekly-report` skill) — e.g. "codebase-audit: project X, 3 new findings, 2 auto-resolved, 5 still open awaiting approval."

## Agent delegation and the wider skill/tool pool

Read `references/agents-and-tools.md` before scanning — it's the canonical, up-to-date mapping of subtask → agent role → skills/tools for this entire skill family (dev-sprint, codebase-audit, nightly-support, daily-weekly-report), and includes the full expanded pool (`clarify`, `computer_use`, `github`, `simplify-code`, `spike`, `architecture-diagram`, and the rest). If dev-sprint's local copy of this reference ever disagrees with this one, treat this one as canonical.

## Opening a ticket from a live session

When the user says something like *"open a ticket for this error"*, *"file
this"*, or *"make a ticket out of that"* — in a **live session with the user
present** — this is what happens.

**Investigate first, then propose, then wait.** In that order, always:

1. **Investigate.** Reproduce it or read the code until you can state what is
   wrong in one sentence. A ticket you cannot explain is a ticket nobody will
   act on.
2. **Propose.** Show the user, in the chat:
   - the project it belongs to and the id the server *would* mint
     (`GET /api/projects/<project>/tickets/next-id` — a preview, not a
     reservation);
   - the title, the severity you would pick **and why**;
   - the description you would file, in full. Not a summary of it.
3. **Wait.** Ask for a yes or a no, and do nothing until you get one. "No" is
   a complete answer — file nothing, change nothing, and do not ask twice.

**Never file without the yes.** Not "the user seemed to want it", not "this
is obviously a bug", not "I'll file it and they can delete it". An LLM
judging "is this a novel, in-scope bug" and filing unattended will eventually
put something wrong into a ledger the user treats as ground truth, and a
ledger that is quietly wrong is worse than one that is incomplete: every
later run reads it as fact.

**This rule is structural, not a matter of tone.** The write lives in the
dashboard (`POST /api/projects/<project>/tickets`) and in `lib/tickets.py`,
and neither is reachable from this skill — you have no path to disk that
bypasses the user's yes. If you find yourself wanting to "just add it to the
ledger", that is the moment to propose instead.

**The id is never yours to choose.** It comes from the server, minted inside
its write lock. A `TK-` id you invent can collide with a real one, and a
`CR-` id would put a ticket in the finding namespace, which is exactly what
the two namespaces exist to keep apart.

**The user may also file it themselves** from the dashboard's Findings tab,
which is the same endpoint. If they say "I'll do it in the dashboard", point
them there and stop — do not file it as well.

## What this skill never does

- Never edits, fixes, or refactors code — read-only, always.
- Never flips the `approved` flag itself — that's the user's call, by hand, in the ledger file.
- Never writes a ticket unattended. A live-session ticket is *proposed* and
  waits for a yes; an autonomous run never proposes at all, because there is
  nobody to answer. Tickets for approved findings are `nightly-support`'s job,
  and it enqueues a task rather than provisioning anything.
