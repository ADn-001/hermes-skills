---
name: nightly-support
description: "Nightly support — turn approved audit findings into tickets and queued dev-sprint work. Scans the ledgers of ONE TO THREE explicitly scoped projects for entries the user approved, groups related findings into fewer larger tickets, and enqueues one dev-sprint task per project for the shared loop to pick up. Use whenever the user says \"nightly support,\" asks what got ticketed overnight, or wants the approved-findings→ticket→cron pipeline triggered or inspected."
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
   enqueue ONE dev-sprint task per project into the shared queue (see Step 4)
        │
        ▼
   mark ledger entries: status=assigned → ticketed, linked_ticket set
```

## Scope: this skill is deliberately narrow

**This skill does not scan every ledger under `/home/user/codereview/`.** It works on a
scope of **one to three projects**, set by the user (or by a scoping `nightly-support`
trigger) and persisted so unattended runs are deterministic.

The reason is not tidiness. A run that sweeps every ledger inherits every project's
problems at once: unrelated stacks, unrelated test commands, unrelated conventions, and —
worst — a plan that interleaves fixes across codebases that have nothing to do with each
other. It also means one project's backlog can starve another's, and a single run can
provision a burst of concurrent sprints on a machine that can only carry one.

### Where the scope lives

`/home/user/codereview/scope.json`, created on first use:

```json
{
  "projects": ["my-project"],
  "max_projects": 3,
}
```

- **`projects`** — up to `max_projects` (default 3) directory names under
  `/home/user/codereview/`, i.e. ledger paths `/home/user/codereview/<name>/ledger.md`.
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
python3 tools/ledger.py find /home/user/codereview/<project>/ledger.md --approved --status new
python3 tools/ledger.py validate /home/user/codereview/<project>/ledger.md
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
python3 tools/ledger.py stale-assigned /home/user/codereview/<project>/ledger.md --older-than-hours 26
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
**one queued dev-sprint task**, which the loop works in order. Write the extra tickets to
disk and link them, but let a single task pick them up sequentially — two sprints on the
same codebase in parallel is how two agents end up editing the same file.

Write the ticket using **the same schema as a ledger entry** (see `codebase-audit`'s `references/ledger-schema.md`) — this is what lets `dev-sprint`'s "Starting fresh" step consume it directly as its input spec without a translation step. A grouped ticket is effectively a small collection of ledger entries bundled with a short cover summary explaining how they relate; write it as a `references/ticket-format.md`-shaped doc (see that reference for the exact shape) at `/home/user/codereview/<project-name>/tickets/<ticket-id>.md`.

## Step 4: Enqueue the dev-sprint task — one per project, no cron

**First: is this project already finished?** Read
`dev-sprint/references/dev-dashboard-ledger.md` and check the project's `sprint`
block:

```python
d = state.sprint_disposition(project["sprint"], current_generation)
if d == "suppressed":   # do not enqueue
```

`suppressed` means `state: finished` **and** `finished_generation` equals the
current generation — the finish still describes the plan on disk. **Stand down.**

Do not enqueue a sprint for a plan that is already complete. Doing so starts the
exact loop the terminal state exists to prevent: the fresh task finds no work,
hits 2 consecutive no-op runs, and triggers a redundant audit — and the user
pays for a full audit every cycle.

`reopenable` (a *differing* `finished_generation`, or none at all) means the plan
changed since the finish, so new phases are waiting. Enqueue normally.

**Getting this backwards blocks all future work on a project** instead of
wasting one audit, so both directions are specified and the unkeyed case counts
as `reopenable`, never `suppressed`. When the answer is not obvious, re-read the
ledger reference — do not guess.

Also skip if the project is absent from the ledger, `path_absent` is true, or
sprint scope is not enabled. Those are the user's decisions.

Once the ticket is written:
- Resolve the target project dir the same way `dev-sprint` does. Project directories are under `/home/user/projects/<name>/`.
- **Enqueue the work as a task in the dashboard ledger, then return.** This skill does not create, arm, schedule, stagger or name a cron job. It never did that safely under a shared loop, and it does not do it now.

#### How to enqueue

`state.json` has exactly one writer — the dashboard server's own save path — and
`state.save()` is that path. Load, append one task, save:

```python
import sys; sys.path.insert(0, "/home/user/projects/dev-dashboard")
from lib import state

path = state.state_path()
doc = state.load(path)
doc.setdefault("tasks", {})["dev-sprint-%03d" % _next_index(doc)] = {
    "kind": "dev-sprint",
    "project": "<project>",
    "title": "<the ticket title>",
    "origin_id": "TICKET-2026-09-25-auth-webhook-hardening",
    "source": "nightly-support",
    "state": "idle",
    "enqueued_at": _now_iso(),
}
state.save(path, doc)   # normalise → validate → temp file → os.replace
```

Read `dev-sprint`'s `references/dev-dashboard-ledger.md` for the exact task
record and the id-derivation rule; it is the same one the dashboard itself
writes, and a hand-rolled id that collides with an existing task is a lost
update. **`state.save()` validates and refuses an invalid document, so a
successful return means the task is in the ledger.** Do not hand-edit
`state.json` and do not write a bare `json.dump` — a partial write there takes
down every reader.

**The interval is not yours to choose.** It was a per-project cron cadence, and
under one shared loop there is no per-project cadence to set: the loop runs at
`cadence.loop_minutes` and the queue decides what is next. A project that
genuinely needs different timing is a user decision, made in the Settings tab,
not something to encode by provisioning a second job.

Hand the ticket to `dev-sprint` as a natural-language spec with no live
back-and-forth — this is the autonomous chain, so `dev-sprint` skips its
brainstorming step and goes straight to recon → plan → gatelog.

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

Mark every grouped entry: `status: assigned` immediately (closes the race window), then `status: ticketed` once `state.save()` has returned, with `linked_ticket` set to the ticket's path/ID. There is no `linked_cron_job` to set — no cron was created, and inventing a job name that does not exist is how the next run goes looking for work that was never scheduled.

Use the surgical rewriter rather than a text edit, so approvals and every other field
survive untouched:

```bash
python3 tools/ledger.py set-status /home/user/codereview/<project>/ledger.md \
    --id CR-<project>-0007 --status ticketed \
    --ticket TICKET-2026-09-25-auth-webhook-hardening
```

If a run dies between the two states, Step 2's `stale-assigned` check recovers it.

## Step 6: Log clearly — this is the safety valve

Because this chain enqueues autonomous coding with no human in the loop after the original approval, always append a clear entry to today's daily report file (see `daily-weekly-report`) summarizing exactly what happened this run: which projects were in scope, what got ticketed (with ticket IDs), what tasks were enqueued, and what got skipped and why (already in flight, nothing approved, stranded-and-recovered, out of scope). This is the only place the user sees this pipeline's activity without having to go dig through ledgers — don't skip it, even on a run where nothing happened ("nightly-support: scope = my-project; nothing approved and new this cycle" is a valid, useful entry).

Keep it to the significant: this is a status channel for codebases and assigned work, not
a per-run heartbeat. One entry per project that did something, plus a single line naming
the projects that were checked and did nothing.

## Closing the loop

When a ticket-originated `dev-sprint` run reaches "All phases complete," it triggers a one-shot `codebase-audit` on that project (see dev-sprint's own completion step, and note its guard: that audit is one-shot per completion, not per invocation). That audit run is what actually flips the corresponding ledger entries to `status: resolved` — `nightly-support` doesn't need to do this itself, but should recognize `resolved` entries on future scans as fully closed, not something to re-ticket.

## Scheduling this skill itself

`nightly-support` runs via cron, but the user sets that cron job up themselves (this skill doesn't self-schedule) — default cadence is once daily. If asked, remind the user of this rather than trying to provision your own recurring invocation.

## Agent delegation and the wider skill/tool pool

Read `codebase-audit`'s `references/agents-and-tools.md` — the canonical, up-to-date mapping for this whole skill family. Ticket-writing itself is usually simple enough to do inline, but grouping decisions on a large ledger, or checking for live sessions, can benefit from `delegation`/`a2a` and `session_search` exactly as the other skills in this family use them.
