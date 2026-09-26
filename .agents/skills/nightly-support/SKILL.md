---
name: nightly-support
description: "Nightly support — turn approved audit findings into tickets and scheduled dev-sprint work. Scans the ledgers of ONE TO THREE explicitly scoped projects for entries the user approved, groups related findings into fewer larger tickets, and provisions one staggered dev-sprint cron per project. Use whenever the user says \"nightly support,\" asks what got ticketed overnight, or wants the approved-findings→ticket→cron pipeline triggered or inspected."
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
   provision ONE dev-sprint cron per project, staggered (see Step 4)
        │
        ▼
   mark ledger entries: status=assigned → ticketed, linked_ticket, linked_cron_job set
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
  "interval": "3h"
}
```

- **`projects`** — up to `max_projects` (default 3) directory names under
  `/home/user/codereview/`, i.e. ledger paths `/home/user/codereview/<name>/ledger.md`.
- **`max_projects`** — hard cap. A fourth project is refused, not silently queued. Raise
  the cap deliberately if the user wants more.
- **`interval`** — the dev-sprint cron cadence, default `3h`.

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
<date>, no ticket and no cron job existed"), so a stranded project is visible rather than
quietly re-adopted. Then proceed with it normally. Do the same for a `ticketed` entry
whose `linked_cron_job` is null — the ticket exists but the job that was to implement it
does not.

Never re-claim entries that a *live* cron owns. The 26-hour default is deliberately
generous: it spans a full day of 3-hour cycles, so ordinary slow work is never mistaken
for a crash.

## Step 3: Group and write the ticket

Group the qualifying findings for a project into **fewer, larger tickets** rather than one ticket per finding — by file or subsystem, whichever grouping makes for a coherent, independently-plannable unit of work. Don't force unrelated findings into one ticket just to minimize count; a project with two unrelated approved findings (say, one security fix in auth and one dead-code cleanup in startup) should become two tickets, not one.

One project may yield several tickets, but see Step 4's stagger rule: a project gets
**one dev-sprint cron**, which works its ticket queue in order. Write the extra tickets to
disk and link them, but let a single cron pick them up sequentially — two sprints on the
same codebase in parallel is how two agents end up editing the same file.

Write the ticket using **the same schema as a ledger entry** (see `codebase-audit`'s `references/ledger-schema.md`) — this is what lets `dev-sprint`'s "Starting fresh" step consume it directly as its input spec without a translation step. A grouped ticket is effectively a small collection of ledger entries bundled with a short cover summary explaining how they relate; write it as a `references/ticket-format.md`-shaped doc (see that reference for the exact shape) at `/home/user/codereview/<project-name>/tickets/<ticket-id>.md`.

## Step 4: Provision the dev-sprint cron — one per project, staggered

**First: is this project already finished?** Read
`dev-sprint/references/dev-dashboard-ledger.md` and check the project's `sprint`
block:

```python
d = state.sprint_disposition(project["sprint"], current_generation)
if d == "suppressed":   # do not provision
```

`suppressed` means `state: finished` **and** `finished_generation` equals the
current generation — the finish still describes the plan on disk. **Stand down.**

Do not provision a sprint for a plan that is already complete. Doing so starts
the exact loop the terminal state exists to prevent: the fresh job finds no
work, hits 2 consecutive no-op runs, provisions a redundant audit, and deletes
itself — and the user pays for a full audit every cycle.

`reopenable` (a *differing* `finished_generation`, or none at all) means the plan
changed since the finish, so new phases are waiting. Provision normally.

**Getting this backwards blocks all future work on a project** instead of
wasting one audit, so both directions are specified and the unkeyed case counts
as `reopenable`, never `suppressed`. When the answer is not obvious, re-read the
ledger reference — do not guess.

Also skip if the project is absent from the ledger, `path_absent` is true, or
sprint scope is not enabled. Those are the user's decisions.

Once the ticket is written:
- Resolve the target project dir the same way `dev-sprint` does. Project directories are under `/home/user/projects/<name>/`.
- Provision a `dev-sprint` cron job against that project dir and ticket, using `cronjob`. Default interval: **every 3 hours** (`scope.json`'s `interval`, or the project's `interval` in the ledger). Only use a different interval if the user explicitly said so.
- **Name it `dev-sprint-<project>-auto-<uid>`** with a real `uuid4().hex[:8]` suffix — not `dev-sprint:<project>`. The `-auto-` infix is the authorisation token that separates the loop's jobs from the user's own; a job without it is not ours and the ownership rules will (correctly) refuse to touch it. See `dev-sprint/references/dev-dashboard-ledger.md`.
- **Arm the job with the skills the work needs** — a bare `--skill dev-sprint` job runs a whole sprint with no TDD, debugging or review tooling, which is the most common reason these jobs underperform. See `dev-sprint`'s `references/cron-prompt.md` for the exact flag list and the reasoning; in short: `dev-sprint`, `test-driven-development`, `systematic-debugging`, `codebase-inspection`, `requesting-code-review`, plus situational ones for the project.
- Hand the ticket to `dev-sprint` exactly as if it were a natural-language spec handed off with no live back-and-forth — this is the autonomous chain, so `dev-sprint` should skip its brainstorming step and go straight to recon → plan → gatelog.
- **Write the real job name and `job_id` back into the dashboard ledger**, replacing the `-auto-00000000` placeholder. Use `state.save()` so the write is validated and atomic — never a text edit or a bare `json.dump`.

### Never provision a second sprint for a project that already has one

Before creating, list jobs and filter to **owned** ones for this project:

```python
mine = ownership.owned_jobs(all_jobs)
```

**If two owned sprint jobs exist for one project, that is a bug, not a choice.**
Pick neither, report it, and let the user resolve it — do not silently keep the
one you find first. Never act on "the first dev-sprint job" or "the job for this
project": a user-created job can share both the skill and the project name.

### Never run two sprints in parallel

Multiple scoped projects means multiple crons, and two agents editing codebases at the
same time on one machine will contend for CPU, memory, model quota and — if the projects
share a checkout or a virtualenv — corrupt each other's state. **Stagger them.**

Give each project a distinct phase of the interval, so no two jobs start together:

| Project (in `scope.json` order) | Cron schedule |
|---|---|
| first | `<interval>` — e.g. `0 */3 * * *` |
| second | the interval, offset into it — e.g. `45 1-22/3 * * *` |
| third | the remainder — e.g. `30 2-23/3 * * *` |

Concretely: divide the interval into equal slices and give project *N* the *N*th slice, so
with a 3h interval the three projects start at :00, :20 and :40 past alternating hours.
With more projects than slices, extend the interval rather than overlapping — three
projects on a 3h interval becomes a 90-minute interval with one start per slice, not three
jobs racing.

Use `cronjob`'s scheduling support for this. Two named jobs must never share a start
minute; if a slot is already taken, push to the next free slice and say so in the report.
This also gives a second, free safety property: jobs landing in different slices rarely
collide with each other's *previous* run, so a slow phase doesn't cascade.

Name jobs `dev-sprint:<project>` so they're identifiable in `hermes cron list` and
removable by name.

## Step 5: Update the ledger

Mark every grouped entry: `status: assigned` immediately (closes the race window), then `status: ticketed` once the cron job is actually provisioned, with `linked_ticket` set to the ticket's path/ID and `linked_cron_job` set to the job name.

Use the surgical rewriter rather than a text edit, so approvals and every other field
survive untouched:

```bash
python3 tools/ledger.py set-status /home/user/codereview/<project>/ledger.md \
    --id CR-<project>-0007 --status ticketed \
    --ticket TICKET-2026-09-25-auth-webhook-hardening --cron dev-sprint:<project>
```

If a run dies between the two states, Step 2's `stale-assigned` check recovers it.

## Step 6: Log clearly — this is the safety valve

Because this chain provisions autonomous coding + cron scheduling with no human in the loop after the original approval, always append a clear entry to today's daily report file (see `daily-weekly-report`) summarizing exactly what happened this run: which projects were in scope, what got ticketed (with ticket IDs), what cron jobs were created, and what got skipped and why (already in flight, nothing approved, stranded-and-recovered, out of scope). This is the only place the user sees this pipeline's activity without having to go dig through ledgers — don't skip it, even on a run where nothing happened ("nightly-support: scope = my-project; nothing approved and new this cycle" is a valid, useful entry).

Keep it to the significant: this is a status channel for codebases and assigned work, not
a per-run heartbeat. One entry per project that did something, plus a single line naming
the projects that were checked and did nothing.

## Closing the loop

When a ticket-originated `dev-sprint` run reaches "All phases complete," it triggers a one-shot `codebase-audit` on that project (see dev-sprint's own completion step, and note its guard: that audit is one-shot per completion, not per invocation). That audit run is what actually flips the corresponding ledger entries to `status: resolved` — `nightly-support` doesn't need to do this itself, but should recognize `resolved` entries on future scans as fully closed, not something to re-ticket.

## Scheduling this skill itself

`nightly-support` runs via cron, but the user sets that cron job up themselves (this skill doesn't self-schedule) — default cadence is once daily. If asked, remind the user of this rather than trying to provision your own recurring invocation.

## Agent delegation and the wider skill/tool pool

Read `codebase-audit`'s `references/agents-and-tools.md` — the canonical, up-to-date mapping for this whole skill family. Ticket-writing itself is usually simple enough to do inline, but grouping decisions on a large ledger, or checking for live sessions, can benefit from `delegation`/`a2a` and `session_search` exactly as the other skills in this family use them.
