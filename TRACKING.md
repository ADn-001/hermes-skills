# TRACKING — hermes-skills

Revision history for the four skills in this repo, and why each change was made.

Most of these fixes came from the same source: the skills had been used for real — a
twelve-phase sprint and a fifty-three-entry findings ledger — and the wear showed. The
bugs that mattered were not typos. They were **loops that never terminate and locks that
never release**, in a system whose whole purpose is to run unattended across many sessions
with no human present to notice.

## v2 — correctness, scoping, and pre-written reports (2026-09-25)

### Correctness: three failure modes that were silent

1. **The completion audit re-fired forever.** Both the skill and its cron prompt told an
   unattended session to trigger a one-shot `codebase-audit` whenever a gatelog read
   "All phases complete". With a recurring cron, that is a full-codebase audit on *every
   invocation*, indefinitely. The first live project had to hand-write a note into its own
   gatelog — "don't run a second one-shot audit unless the ledger is gone" — which is
   exactly the guard the skill should have shipped with. Now: a three-way check before
   auditing, and the fact is recorded in the gatelog so the next session sees it. The
   ledger's `Last run:` date is the durable marker.

2. **`status: assigned` deadlocked a project permanently.** `nightly-support` marks
   entries `assigned` before writing the ticket, to stop two runs double-claiming the same
   finding. But nothing in the family ever moved `assigned` back to `new`, so a run that
   died in that window left the project looking busy *forever* and its approved findings
   were never ticketed again. `assigned` is now documented as a lock with a timeout rather
   than a queue position, and `ledger.py stale-assigned` is the detector.

3. **The resume check was case-sensitive.** It looked for lowercase `plan.md`. Projects
   created by older tooling use `PLAN.md`, which that check read as *no plan at all* — a
   brand-new project. On one live project it meant re-planning sixteen completed phases.
   `gatelog_check.py locate` now finds the files case-insensitively and reports whether
   the gatelog is canonical (`### Findings`) or legacy (`### info to know`).

### Scoping: nightly-support is now narrow on purpose

It used to scan *every* ledger under the review root, so one run could juggle unrelated
codebases, interleave fixes across projects with nothing in common, let one project's
backlog starve another's, and provision a burst of concurrent sprints on a machine that
can only carry one.

- It now works from an explicit scope of **one to three projects** (`scope.json`), set by
  the user. Unattended with no scope file, it does nothing and says so.
- **One cron per project, staggered** — each project gets a different slice of the
  interval, so no two sprints start together and a slow phase doesn't cascade into the
  next job's run.

### Arming: cron jobs now carry the skills the work needs

A sprint job was being provisioned with only `--skill dev-sprint`, so the whole sprint ran
with no TDD, no debugging skill, no review pass and no code-inspection tooling, and
discovered mid-phase that it needed them. `cron-prompt.md` now carries the full
provisioning block, with the reasoning for each attached skill.

### Reports: pre-written, not summarised on demand

Asking "what happened today?" used to spin a model run, read the logs, and summarise —
slow, and a thinner answer each time. Two cron jobs now write a daily and a weekly report
file on a schedule; the bridge serves those files directly, so the common case is a file
read: instant, free, and identical every time. A model run stays the fallback for a
missing or stale file, and a file that predates the newest log entry is never presented as
current.

The log itself was too noisy to serve as a status channel — one day held 42 entries of
routine bridge operations and almost nothing about the work. The skill now has an explicit
in/out table and one test: *would the user be surprised to hear this a week from now?*

### Tooling

`tools/ledger.py` and `tools/gatelog_check.py` — stdlib-only, no dependencies, 90 tests.
Every subcommand takes `--json`; exit codes are `0` clean / `1` problem / `2` usage.
Read-only subcommands never write, not even an mtime. The ledger rewriters are surgical:
changing one entry's status in a 95 KB ledger edits exactly two lines and leaves every
other byte alone, which is what keeps a human's approvals intact.

Building the validators also **found a real defect in live project state**: a phase that
had been implemented and marked done was missing from its `plan.md` entirely. Prose said
"the gatelog mirrors the plan"; a validator notices.

### Housekeeping

- `references/agents-and-tools.md` existed in two skills with different content and had
  already drifted. It is now one canonical copy with a pointer from the other — a
  duplicated reference is maintained zero times and trusted twice.
- The ledger schema now includes `covered_by_test`, which was present on all 53 entries of
  the first live ledger but absent from the schema that claimed to be authoritative.
- `category`/`severity` are documented as free prose on purpose; forcing a narrow
  vocabulary loses the specific thing that makes a finding findable.

## Verification

- `python3 -m unittest discover -s tools/tests` — 90 tests, all passing.
- `ledger.py validate` — 53 real entries, 0 problems.
- `gatelog_check.py locate` on a legacy-dialect project — finds `PLAN.md`, reports
  `dialect=legacy`, reads all 16 phases.
- `stale-assigned` — flags a 95-hour-old claim with no ticket; leaves a 2-hour-old claim
  and a properly ticketed entry alone.
- Ledger rewrite on a copy of the real ledger — a 2-line diff in a 95 KB file.
- Consumer suite (the voice bridge that reads these reports): 298 tests green.
