---
name: nightly-support
description: "Nightly support — turn approved audit findings into tickets AND planned dev-sprint phases. Scans the ledgers of ONE TO THREE explicitly scoped projects for entries the user approved, groups related findings into fewer larger tickets, writes each ticket to disk, appends the implementing phases to the project's gatelog, and re-opens the project so the shared loop can pick them up. Use whenever the user says \"nightly support,\" asks what got ticketed overnight, or wants the approved-findings→ticket→phase pipeline triggered or inspected."
---

# Nightly Support

The bridge between `codebase-audit`'s findings ledger and `dev-sprint`'s implementation cycle. Runs once a day, reads only what the user has explicitly approved, and hands work off to `dev-sprint` without re-doing anything already in flight.

```
codebase-audit ledger (approved:true, status:new)
        │   ← only within THIS skill's scope (1-3 projects)
        ▼
   group related findings per project
        │
        ▼
   write ticket (same schema as a ledger entry)
        │
        ▼
   check no dev-sprint already in flight for this project  ──▶ if in flight: skip, wait for next run
        │
        ▼
   write the implementing phases into the project's gatelog (see Step 4)
   →  re-open the project so the shared loop may provision them
        │
        ▼
   mark ledger entries: status=assigned → ticketed, linked_ticket set
```

## Where things live

Two paths, resolved once at the top of a session. They are variables rather
than literals because this repository is shared: an absolute path in a skill
resolves on exactly one machine and fails *silently* — a command pointed at a
directory that does not exist does not raise, it reads nothing and reports
nothing found.

- **`$CODE_REVIEW`** — the shared findings root holding one
  `<project-name>/ledger.md` per project, plus `scope.json`. A **sibling** of
  `$PROJECTS`, not inside it. Find it with
  `find ~ -maxdepth 3 -name 'ledger.md' -path '*codereview*'`.
- **`$PROJECTS`** — the directory that *contains* project checkouts. Find it
  with `find ~ -maxdepth 3 -type d -name dev-dashboard`.

`codebase-audit` defines the same two variables the same way.

## Scope: this skill is deliberately narrow

**This skill does not scan every ledger under `$CODE_REVIEW/`.** It works on a
scope of **one to three projects**, set by the user (or by a scoping `nightly-support`
trigger) and persisted so unattended runs are deterministic.

The reason is not tidiness. A run that sweeps every ledger inherits every project's
problems at once: unrelated stacks, unrelated test commands, unrelated conventions, and —
worst — a plan that interleaves fixes across codebases that have nothing to do with each
other. It also means one project's backlog can starve another's, and a single run can
provision a burst of concurrent sprints on a machine that can only carry one.

### Where the scope lives

`$CODE_REVIEW/scope.json`, created on first use:

```json
{
  "projects": ["my-project"],
  "max_projects": 3,
}
```

- **`projects`** — up to `max_projects` (default 3) directory names under
  `$CODE_REVIEW/`, i.e. ledger paths `$CODE_REVIEW/<name>/ledger.md`.
- **`max_projects`** — hard cap. A fourth project is refused, not silently queued. Raise
  the cap deliberately if the user wants more.

**How the scope is chosen when it doesn't exist yet:**

- *Interactive session* — ask the user which projects to track, with the actual list of
  ledgers found on disk as the choices. Never guess.
- *Unattended/cron run with no scope file* — do **nothing** and log that the scope is
  unset. An unscoped run is exactly the failure mode this section exists to prevent;
  silently defaulting to "all projects" would reintroduce it on the very first run.

Set or change the scope when the user asks ("track these two projects", "drop X from the
list"), and when a scoped project disappears from disk, drop it from the file and say so.

## Step 1: Scan ledgers (scoped only)

Read every ledger named in `scope.json` — and **only** those. If a scoped project has no
ledger yet, note it and move on; that is a normal state, not an error.

Use the `tools/ledger.py` helper from this skill's repo when it is available — it parses
the ledger and answers exactly this question without an LLM re-reading the file:

```bash
python3 tools/ledger.py find $CODE_REVIEW/<project>/ledger.md --approved --status new
python3 tools/ledger.py validate $CODE_REVIEW/<project>/ledger.md
```

Filter to entries where `approved: true` **and** `status: new`. Anything else
(`assigned`, `ticketed`, `resolved`, `rejected`, or `approved: false`) is out of scope for
this run — never re-process it.

## Step 2: Backpressure check, before writing anything

For each project with qualifying entries, check **both** of these before proceeding — either one blocking is enough to skip that project this run:

1. **Ledger-level:** does this project already have entries at `status: assigned` or `status: ticketed`? If so, a dev-sprint is already provisioned or about to be — skip; the newly-approved findings wait in the queue until that run finishes (its completion will trigger a follow-up `codebase-audit`, which is when those older entries resolve and the ledger clears for this project again).
2. **Live-session-level:** even if the ledger looks clear, use `session_search`/`delegation`/`a2a` to check whether a `dev-sprint` session is actually running against that project dir right now (covers a human having kicked one off by hand, outside the ledger's knowledge). If so, skip.

Only proceed to Step 3 for projects that pass both checks.

### Un-stick a stranded project (do this before skipping)

`assigned` is a claim, not a verdict. A previous run that died between marking entries
`assigned` and provisioning the cron leaves the project looking busy forever — nothing
else in this skill family ever moves `assigned` back to `new`, so the deadlock is silent
and permanent.

So before skipping a project on rule 1, **check how long it has been claimed**:

```bash
python3 tools/ledger.py stale-assigned $CODE_REVIEW/<project>/ledger.md --older-than-hours 26
```

An `assigned` entry older than that with no `linked_ticket` is not in-flight work; it is
the residue of a crashed run. Treat the project as clear and **say so explicitly in the
daily report** ("recovered project X: N entries were stranded in `assigned` since
<date>, no ticket and no queued task existed"), so a stranded project is visible rather
than quietly re-adopted. Then proceed with it normally. Do the same for a `ticketed`
entry with no task in the dashboard queue — the ticket exists but nothing is scheduled to
implement it.

Never re-claim entries that a *running* task owns. The 26-hour default is deliberately
generous: it spans a full day of `loop_minutes` cycles, so ordinary slow work is never
mistaken for a crash.

## Step 3: Group and write the ticket

Group the qualifying findings for a project into **fewer, larger tickets** rather than one ticket per finding — by file or subsystem, whichever grouping makes for a coherent, independently-plannable unit of work. Don't force unrelated findings into one ticket just to minimize count; a project with two unrelated approved findings (say, one security fix in auth and one dead-code cleanup in startup) should become two tickets, not one.

One project may yield several tickets, but see Step 4's rule: a project gets
**one set of phases**, which the loop works in order. Write the extra tickets to
disk and link them into the phases that cover them, but let the single sequence
pick them up — two sprints on the same codebase in parallel is how two agents
end up editing the same file.

Write the ticket using **the same schema as a ledger entry** (see `codebase-audit`'s `references/ledger-schema.md`) — this is what lets `dev-sprint`'s "Starting fresh" step consume it directly as its input spec without a translation step. A grouped ticket is effectively a small collection of ledger entries bundled with a short cover summary explaining how they relate; write it as a `references/ticket-format.md`-shaped doc (see that reference for the exact shape) at `$CODE_REVIEW/<project-name>/tickets/<ticket-id>.md`.

## Step 4: Plan the phases — this is the step that makes the tickets real

A ticket on disk is a description. Nothing works it. **This step is the reason
the pass exists**, and skipping it is the failure that looks like success: the
run writes tidy tickets, reports "nothing enqueued because the plan is
complete", and the project's real bugs stay unfixed forever while every run
claims a clean bill of health.

So: for each ticket, write the phase that will implement it, into the project's
own gatelog, using the `dev-sprint` phase format. That skill is loaded for this
pass precisely because the format is its specification.

### The plan being complete is not a reason to stop

This is the part that used to be backwards. An earlier version read the
project's sprint block, saw `state: finished`, and **stood down** — on the
reasoning that enqueueing a sprint for a complete plan wastes an audit cycle.

That reasoning was correct *for enqueueing* and wrong for the job as a whole. A
`finished` project with fresh approved findings is not a finished project; it is
a project whose audit found things nobody has turned into work yet. Standing
down guaranteed the findings never got worked, because nothing else in the
system was going to write the phases.

The rule now:

1. **Write the phases first.** Append them to the gatelog, numbered from the
   next free number, in the `dev-sprint` format, each naming the tickets it
   covers and what "done" is.
2. **Then move the pointer**, to your first new phase — and to nothing else. If
   you wrote no phases, leave the pointer byte-for-byte as you found it.
3. **Then clear the finished flag**, so the loop may provision the phases:

   ```
   POST /api/projects/<name>/reopen
   ```

   This route refuses with a 409 when the plan still reads as complete. **That
   refusal is your diagnostic, not an obstacle.** It means your phases did not
   land or did not parse. Fix the gatelog — in practice the `Status:` line is
   missing or misspelled, and one unreadable phase makes `read_gatelog` raise
   and the whole file look absent. Never hand-edit `state.json` to force past it.

Appending phases also moves the plan's generation fingerprint, so the flag
clears by itself on the next ledger write. Call the route anyway: it tells you
immediately that the phases took, instead of leaving you to assume.

### Never renumber, and never write a phase as done

Existing phases keep their numbers; a renumbered gatelog invalidates every
branch name and every "see Phase N" note that cites one. And a phase you write is
work that has not happened — `read_gatelog` counts anything not `done` as
unstarted, and that count is the only thing proving there is work to do.

### One phase set per project

Bundle related findings into as few phases as the work honestly allows. A
phase is a coherent change, not a finding: two unrelated fixes in auth and in
startup are two phases, not one. Cross-link the tickets each phase covers.

### Do not spawn a session to do this

You have everything a planning session would need. Write the phases yourself —
a second agent reasoning about the same checkout is the collision the rest of
this system is built to prevent.

### Never provision a cron from this skill, under any conditions

This is the rule that replaced the old provisioning step, and it is absolute:

- **No `cronjob` create.** Not for a project, not for a "just this once", not
  because the queue looks slow. One shared loop drains the queue; a second job
  runs the same work twice.
- **No per-project cadence.** Two jobs on one machine contend for CPU, memory
  and model quota, and if the projects share a checkout or a virtualenv they
  corrupt each other's state. The queue serialises them, which is the entire
  reason it exists.
- **No naming and arming.** The `-auto-<uid>` infix, the skill flag list and the
  start-minute staggering all belonged to the one-cron-per-project design and
  have no meaning here. The loop is armed once, by the user, through the
  dashboard's apply flow.

If a run finds two owned sprint jobs for one project, that is a **bug, not a
choice** — report it and let the user resolve it. Do not silently keep the one
you find first, and never act on "the first dev-sprint job": a user-created job
can share both the skill and the project name.

## Step 5: Update the ledger

Mark every grouped entry: `status: assigned` immediately (closes the race window), then `status: ticketed` once the ticket is on disk **and Step 4's reopen route has returned 200**, with `linked_ticket` set to the ticket's path/ID. There is no `linked_cron_job` to set — no cron was created, and inventing a job name that does not exist is how the next run goes looking for work that was never scheduled.

Use the surgical rewriter rather than a text edit, so approvals and every other field
survive untouched:

```bash
python3 tools/ledger.py set-status $CODE_REVIEW/<project>/ledger.md \
    --id CR-<project>-0007 --status ticketed \
    --ticket TICKET-2026-09-25-auth-webhook-hardening
```

If a run dies between the two states, Step 2's `stale-assigned` check recovers it.

## Step 6: Log clearly — this is the safety valve

Because this chain enqueues autonomous coding with no human in the loop after the original approval, always append a clear entry to today's daily report file (see `daily-weekly-report`) summarizing exactly what happened this run: which projects were in scope, what got ticketed (with ticket IDs), what phases were appended (with their numbers and the project re-opened), and what got skipped and why (already in flight, nothing approved, stranded-and-recovered, out of scope). This is the only place the user sees this pipeline's activity without having to go dig through ledgers — don't skip it, even on a run where nothing happened ("nightly-support: scope = my-project; nothing approved and new this cycle" is a valid, useful entry).

Keep it to the significant: this is a status channel for codebases and assigned work, not
a per-run heartbeat. One entry per project that did something, plus a single line naming
the projects that were checked and did nothing.

## Closing the loop

When a ticket-originated `dev-sprint` run reaches "All phases complete," it triggers a one-shot `codebase-audit` on that project (see dev-sprint's own completion step, and note its guard: that audit is one-shot per completion, not per invocation). That audit run is what actually flips the corresponding ledger entries to `status: resolved` — `nightly-support` doesn't need to do this itself, but should recognize `resolved` entries on future scans as fully closed, not something to re-ticket.

## Scheduling this skill itself

`nightly-support` runs via cron, but the user sets that cron job up themselves (this skill doesn't self-schedule) — default cadence is once daily. If asked, remind the user of this rather than trying to provision your own recurring invocation.

## Agent delegation and the wider skill/tool pool

Read `codebase-audit`'s `references/agents-and-tools.md` — the canonical, up-to-date mapping for this whole skill family. Ticket-writing itself is usually simple enough to do inline, but grouping decisions on a large ledger, or checking for live sessions, can benefit from `delegation`/`a2a` and `session_search` exactly as the other skills in this family use them.
