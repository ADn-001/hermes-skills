---
name: dev-sprint
description: "Dev sprints: phased, resumable builds behind all-green test gates. Use whenever the user wants to build or extend a feature via \"dev sprints,\" \"phased plan,\" \"gatelog,\" or an autonomous/cron-driven multi-session build; to resume an in-progress phased build (existing plan.md + gatelog.md in a project dir); or to kick one off from a natural-language idea, a spec/ticket, or a target project folder. Always check for an existing gatelog.md before planning from scratch — this skill is idempotent and must resume rather than replan when one is found."
---

# Dev Sprint

A workflow for building features through autonomous, resumable, phase-by-phase sprints — each phase ends at an all-green e2e test gate before the next begins. Designed to survive being run across many separate sessions (including unattended cron-job calls) because all state lives on disk, not in conversation memory.

## The core loop

```
RECON  →  PLAN  →  [ DEV SPRINT → TEST/DEBUG SPRINT ]×N per phase  →  GATE UPDATE  →  next phase
```

Three files drive everything, all in the project dir:
- **report.md** — one-time recon findings from the initial codebase/context scan
- **plan.md** — the phase-by-phase plan, each phase broken into actionable tasks plus a final e2e test gate
- **gatelog.md** — the single source of truth for progress: which phases are done, which is next, and a findings section per phase

Read `references/file-formats.md` before creating or editing any of the three files — it has the exact templates and field meanings.

## Step 0: Resolve the target project dir (idempotency check — always do this first)

1. **If the user gave a path**, use it.
2. **If no path was given**, look locally for a directory that matches the task's name or subject. If nothing plausible is found, create a new project dir (short kebab-case name derived from the task).
3. **Inside that dir, locate `gatelog.md` and `plan.md` — CASE-INSENSITIVELY.**

   Do this by hand-listing the dir (`search_files` for `*.md`, or `ls`) and matching the
   names case-insensitively. Do **not** test for the literal lowercase paths only: projects
   created by older tooling use `PLAN.md`/`REPORT.md`, and a case-sensitive check reads
   those as a fresh start and silently discards a completed plan. A live project on the
   author's own machine is a real example — 16 phases, uppercase filenames.

   Where the `tools/` scripts from this skill's repo are available, `gatelog_check.py locate
   <dir>` does this and additionally reports whether the gatelog is in the canonical dialect
   (`### Findings`) or the legacy one (`### info to know`). Prefer it when present.

   - **Both exist →** this is a resume. Skip straight to "Resuming a run" below. Do NOT re-plan, do NOT re-run recon, do NOT overwrite report.md.
   - **Neither exists →** this is a fresh start. Go to "Starting fresh" below.
   - **Only one exists (rare/corrupted state)** → read whichever exists, infer what's missing as best you can, note the inconsistency at the top of gatelog.md's Notes section, and proceed as a resume.

This check is mandatory and comes before anything else, including before asking the user clarifying questions — the files on disk are more trustworthy than assumptions about session history.

**Legacy gatelogs.** A gatelog written by an older prompt may use `### info to know` where
this skill writes `### Findings`, and may carry phases whose `Status:` line is missing. It
is still a valid resume target — **never re-plan a project that has phases on disk.** Read
the phase list as it stands, treat a missing `Status:` as `not started`, and append any
missing structure rather than rewriting history. If you add canonical structure, say so in
`## Notes`.

## Starting fresh

Triggered when there's no plan.md/gatelog.md, and the user gave either: a target dir with no state files, a natural-language idea, or a formatted spec/ticket.

**0. Brainstorm first — but only in a live, human-driven session.** If a human is actually present and typing (not a cron/autonomous invocation, and not a ticket handed over by `nightly-support`), do not jump straight to recon. Have a short back-and-forth first: propose an implementation approach, offer your own improvement suggestions, and use the `clarify` tool to ask the user questions until the important details are pinned down (scope, constraints, must-haves vs nice-to-haves). Only once that's settled do you move into recon → plan → gatelog. Skip this step entirely for: autonomous/cron kickoffs, and specs arriving from `nightly-support` (those have already been through review/approval — treat the ticket as settled and go straight to recon).

1. **Recon.** Do a codebase-wide (or context-wide, if there's no existing code) scan relevant to the task: existing structure, conventions, relevant files, constraints, open questions. Write it to `report.md` (template in references/file-formats.md). This is written once and is never overwritten by later phases — later phases may append to it if the agent discovers something recon missed, but they append, they don't rewrite.
2. **Plan.** Break the work into phases. Each phase gets:
   - A short name and goal
   - A list of actionable, concrete tasks (not vague — an implementing agent with no other context should be able to pick up one task and know exactly what to do)
   - A final **e2e test gate**: the specific end-to-end (and regression) test criteria that must pass, all green, before the phase counts as done
   Write this to `plan.md`. Phases should be ordered so each is independently completable and testable — avoid phases that can only be verified once a later phase also lands.
3. **Initialize the gatelog.** Write `gatelog.md` with one entry per phase from the plan, all marked `not started`, findings sections empty. This is the file every future session (including cron calls) reads first.
4. Confirm the plan with the user if this is an interactive session. If this was kicked off to run autonomously/via cron, proceed straight to the first phase instead of waiting.

## Resuming a run

Triggered whenever gatelog.md and plan.md already exist — whether called interactively or from a cron job.

1. **Read all three files**: gatelog.md, plan.md, and report.md (if present).
2. **Don't trust the gatelog blindly.** A prior session (especially a cron-triggered one) may have exited mid-phase without updating it. Before doing anything else:
   - Find whatever test suites already exist for this project (look for the phase's e2e/regression tests referenced in plan.md or gatelog.md).
   - Run them one by one, plus the full regression suite.
   - Use the results to determine the *actual* current state of the codebase — which phase is really done, which is in progress, and whether the previous agent left anything broken or half-finished.
   - If this contradicts what gatelog.md says, trust the test results and correct the gatelog entry (with a note explaining the correction) before proceeding.
3. **Identify the next phase that needs work** (first phase in gatelog.md that isn't marked done).
4. Proceed to that phase's **Dev Sprint**, below.
5. **Do exactly one phase per invocation.** Once that phase reaches all-green and the gatelog is updated, stop — do not cascade into the next phase automatically. (This matches the cron-job model in references/cron-prompt.md, where each cron call is one phase.)

## Dev Sprint (implementing one phase)

1. Pull the phase's task list from plan.md.
2. Implement each task.
3. Write an end-to-end test suite for this phase (plus whatever regression tests are needed to make sure this phase didn't break earlier ones). Tests should encode the phase's e2e test gate from plan.md as closely as possible.
4. Hand off to the Test/Debug Sprint — don't mark anything done yet.

## Test/Debug Sprint (looped until green)

1. Run the phase's e2e test suite plus the full regression suite.
2. If anything fails: diagnose, fix, and re-run. Loop this step until everything is green.
3. Log any notable quirks, gotchas, or discoveries along the way — these go into the phase's findings section in gatelog.md, not lost to the session's own memory. This is what lets the *next* agent (possibly a fresh cron session with zero conversational context) avoid re-discovering the same landmine.
4. Once all green: update `gatelog.md` immediately — mark the phase done, fill in its findings section, and set the "next phase" pointer. Do this before ending the sprint, not as an afterthought.

## Findings section (per phase, in gatelog.md)

Every phase entry in gatelog.md must have a findings section the implementing agent fills in during its Test/Debug Sprint. This is free-form notes for the next agent: quirks in the codebase, tricky edge cases, things that looked done but weren't, decisions made that a future phase needs to respect, anything that would otherwise be re-learned the hard way. Terse is fine; omitting it is not.

## Spawning agents

Whatever session is running this skill — interactive or cron — should not do everything in a single thread of thought. Spawn subagents/delegated agents whenever a piece of work is naturally separable, and treat this as the default, not an exception. Read `references/agents-and-tools.md` before a Dev Sprint or Test/Debug Sprint that involves more than trivial work — it lists which kind of subtask maps to which agent role (code review, test writing, debugging, documentation, code writing, investigation, etc.) and which tools/skills each role should reach for.

In short: don't do a whole phase solo in one long undifferentiated pass if it can instead be split into a code-writing pass, an independent code-review pass, a test-writing/TDD pass, a debugging pass, and a docs pass — each spawned as its own agent with a scoped task. This is especially important for cron/unattended runs, which have no human in the loop to catch a single overloaded agent missing something.

**Pitfall: keep each `delegate_task` call's arguments small (under ~8K tokens).** Writing a full
phase spec inline in the `context` field overflows the call and the stream times out before it is
delivered — the spawn never happens and nothing is written. Instead `write_file` the complete
self-contained spec to disk (e.g. `docs/plans/phaseN-workstream-A.md`), then dispatch with a short
`goal` + a `context` that only says "read that file and follow it to the letter" plus the
constraints (files owned, do-not-commit, do-not-run-the-other-suite, report RED/GREEN evidence).
Delete those scratch specs before committing: they contain absolute local paths, and tracked files
must stay share-ready.

**Pitfall: children self-report success — verify the seam they could not test.** A mocked frontend
suite plus a urllib/python suite can both be green while the real frontend client against the real
server is untested. After integrating, run one small probe that drives the shipped client code
against the shipped server process, and re-run the FULL suite yourself on the final tree.

**Pitfall: in a cron/unattended session the shell guard blocks `python3 -c` and heredocs**
(`python3 - <<EOF` / `-c "..."` come back as "flagged as dangerous ... cron jobs run without a
user present"). Don't burn calls working around it: `write_file` the script to `/tmp/foo.py`,
then run `python3 /tmp/foo.py`. Same for parsing or generating state files — a script on disk is
also re-runnable when a phase needs a second pass.

**Pitfall: a subagent's summary is head+tail truncated in the parent result** (the truncation
footer names the full file under `~/.hermes/cache/delegation/subagent-summary-*.txt`, and the
marker is inserted mid-JSON, so `json.loads` fails). When a child returns structured JSON and
parses badly, read the full file from the footer path rather than re-spawning the child — the
complete answer is already on disk.

## Available skills and tools — use them, don't reimplement them

This environment ships additional skills and tools that this skill's workflow should actively pull in rather than working around. Do not hand-roll something (a debugging loop, a code inspection pass, a test harness) that one of these already does.

**Read `references/agents-and-tools.md` for the full mapping.** It is a pointer to the single canonical copy in `codebase-audit/references/agents-and-tools.md` — deliberately not a second table, because two copies of a reference drift and then get trusted twice.

**The most common way a sprint job underperforms:** it was provisioned with only `--skill dev-sprint`, so the whole sprint runs with no TDD, no debugging skill, no review pass and no code-inspection tooling loaded, and discovers mid-phase that it needs them. Provision with the full stack — see `references/cron-prompt.md`.

## Cron / unattended usage

If the user wants this run autonomously across repeated scheduled calls (e.g. a cron job), give them the prompt template in `references/cron-prompt.md` — it's written to be pasted as-is into a scheduled job and already encodes the resume-and-verify behavior from "Resuming a run" above.

## When all phases are complete

Check gatelog.md's "Next phase to work on" line. Once it reads "All phases complete," this skill's own implementation work is done. **The audit handoff below is one-shot per completion, not per invocation** — see the guard before you trigger anything.

### The completion-audit guard (read this before triggering an audit)

A recurring dev-sprint cron keeps firing after the project is done. Without a guard, every
single invocation would launch a fresh full-codebase audit — an expensive, unbounded loop
that re-reads the whole project on a schedule forever.

**So before triggering the one-shot `codebase-audit`, check whether it already ran for this
completion.** All three of these are sufficient evidence it already happened — if any
holds, do NOT audit again:

1. The gatelog's `## Notes` records a completion audit (date + what it found). A prior
   agent may have written this by hand precisely because the skill had no guard — honour it.
2. `/home/user/codereview/<project-name>/ledger.md` exists **and** its `Last run:` date is on
   or after the date the gatelog reached "All phases complete." The ledger is the audit's
   own output: if it exists and postdates completion, the audit has already run.
3. The ledger exists and every entry is `status: resolved` — nothing left to find.

If none holds, the audit has not run for this completion: trigger it, then **write the fact
into the gatelog's `## Notes`** (date, ledger path, finding count) so the next invocation
sees it immediately. Recording it is not optional — the next cron session has no memory
beyond these files, so an unrecorded audit is an audit that runs again.

Never delete or rewrite the ledger to "reset" this. A ledger's approvals and history
outlive the sprint that produced it.

### The handoff itself

Don't just stop silently — hand off depending on how this run was started:

- **Finished interactively, in one live session with the user present:** ask them — *"Want a recurring `codebase-audit` cron for this project? What interval?"* Default to every 10 hours if they say yes without giving a number. Use `cronjob` to set it up if they confirm. Tell them the audit is one-shot; a *recurring* audit cron is a separate, deliberate choice they are making.
- **Handed off mid-way** (user said something like "I'm going away, take over, run every N hours") and the phases finish across later cron calls: no need to ask — trigger the one-shot `codebase-audit` on the project dir directly once the last phase goes green (subject to the guard above), then stop. If the user set up a recurring dev-sprint cron for this project, leave it running (it'll simply have nothing to do until a future phase or ticket adds more to plan.md); note in the log entry (see below) that the project reached "all phases complete" and that the completion audit already ran. **A "nothing to do" invocation must also honour the guard — that is precisely the invocation that would otherwise re-audit.**
- **Autonomous / ticket-driven** (kicked off by `nightly-support`, or a spec handed off with no live back-and-forth): same as the mid-way case — trigger a one-shot `codebase-audit` automatically on completion, no need to ask.

If this project's ledger entries in `codebase-audit`'s ledger were the reason this dev-sprint run exists (i.e. it originated from a `nightly-support` ticket), the triggered `codebase-audit` run closing the loop is what lets `nightly-support` mark those entries `resolved` next time it runs — don't skip this step for ticket-originated work.

## Logging to the daily report

At the end of every task cycle — whether that's finishing a phase, finishing all phases, or a cron call that found nothing to do — append a short entry to today's daily report file. See the `daily-weekly-report` skill for the exact location and format; a few lines is enough ("dev-sprint: project X, phase 2 of 4 done, all green" or "dev-sprint: project X cron call, nothing to do, gatelog already complete"). This is what lets `daily-report`/`weekly-report` summarize what happened without you needing to do anything extra at query time.

## Available skills and tools — the full pool

The expanded pool of skills and tools this skill's workflow can draw on lives in one place:
the canonical `references/agents-and-tools.md` (in `codebase-audit`, the family's canonical
copy). It carries the subtask→role→skill table, the reasoning for each entry, and the
situational Hermes-infrastructure skills.

Situational notes worth keeping in view here:

- **`clarify`** — use it in the brainstorming step above, and any other time a question
  needs a direct answer from the user rather than being guessed at. In a cron session
  there is no user, so it is unavailable and the plan must be unambiguous on its own.
- **`github` / `github-push-pr`** — when the project is git-based, land phase work as a PR
  rather than just committing locally, if the project's conventions call for it.
- **`simplify-code`** — a code-writing or review pass that turned up unnecessary complexity.
- **`spike`** — for a genuinely unknown design question, before committing to an approach.
- **`architecture-diagram`** — when a phase changes structure enough that a diagram helps
  future phases (or humans) more than prose.
- **`docker-service-triage`, `node-inspect-debugger`** — situational additions to the
  debugging role, alongside `systematic-debugging` / `python-debugpy`.
- **Hermes-infrastructure skills** (`hermes-agent`, `hermes-gateway-troubleshooting`,
  `hermes-provider-plugins`, `inspecting-hermes-desktop-dom`, …) — situational, not standard
  dev-sprint roles. Reach for them only when the project being worked on is Hermes itself.

## Output

When this skill produces or updates report.md, plan.md, or gatelog.md, present the current state of the project dir's files inline and let the user know where the dir lives. If asked to package the project (or its state files) for download, zip the project dir and present that.
