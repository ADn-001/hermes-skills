# File formats

Exact templates for the three state files. Keep field names consistent — future sessions (including cron-triggered ones with no conversation context) parse these by convention, not by re-reading prose.

## report.md — one-time recon findings

```markdown
# Recon Report — <task/feature name>

Date: <date first written>

## Scope
<what this task covers, in a sentence or two>

## Existing codebase / context notes
- <relevant files, structure, conventions found>
- <relevant files, structure, conventions found>

## Constraints & decisions
- <any constraint discovered or decision made during recon>

## Open questions
- <anything unresolved that plan.md needs to account for>

---
## Appended findings (post-recon)
<later phases append here if they discover something recon missed. Never rewrite the sections above.>
```

## plan.md — phase-by-phase plan

```markdown
# Plan — <task/feature name>

## Phase 1: <short name>
**Goal:** <one sentence>

**Tasks:**
1. <concrete, actionable task>
2. <concrete, actionable task>
3. ...

**E2E test gate:** <the specific end-to-end + regression criteria that must be all-green before this phase is done. Be concrete: what scenario, what expected result.>

## Phase 2: <short name>
**Goal:** ...

**Tasks:**
1. ...

**E2E test gate:** ...

<... one block per phase ...>
```

Order phases so each is independently verifiable — avoid a phase whose test gate can only pass once a later phase also exists.

## gatelog.md — the source of truth for progress

```markdown
# Gatelog — <task/feature name>

Next phase to work on: <Phase N name, or "All phases complete">

## Phase 1: <short name>
Status: not started | in progress | done
Test suite: <path to this phase's e2e test file(s)>

### Findings
<filled in during the Test/Debug Sprint once this phase goes green. Quirks, gotchas, decisions the next phase must respect. Leave literally empty (not "N/A") until the phase is actually done.>

## Phase 2: <short name>
Status: not started
Test suite: <path, once written>

### Findings


<... one block per phase, mirroring plan.md's phases exactly ...>

## Notes
<any cross-cutting notes — e.g. a correction made after discovering the gatelog was stale on resume>
```

**Rules an implementing agent must follow:**
- Update "Next phase to work on" every time a phase's status changes.
- Never mark a phase `done` without all-green test results backing it up.
- Findings are written by whichever agent actually ran that phase's Test/Debug Sprint — don't write them speculatively before the phase is done.
- If you discover on resume that the gatelog was wrong (previous session exited early, didn't update it, etc.), correct the entry and add a one-line note under `## Notes` explaining what you found and why you corrected it.

## Legacy gatelogs — read this before you "fix" an old one

Gatelogs predating this skill were written by an ad-hoc prompt and differ in ways that
matter, because a case-sensitive or format-sensitive reader will misread them as a fresh
project:

| | canonical | legacy |
|---|---|---|
| findings heading | `### Findings` | `### info to know` |
| plan/report filenames | `plan.md`, `report.md` | `PLAN.md`, `REPORT.md` |
| next-phase pointer | `Next phase to work on: …` | often a bolded `**Phase N — …**` line |
| phase status | a `Status:` line per phase | a `- [x]` checkbox list |

**A legacy gatelog is still a valid resume target.** Never re-plan a project that has
phases on disk, and never rewrite one into canonical form just to tidy it — the history
in it is the only record of what previous sessions actually did. When you add to a legacy
gatelog, match the dialect already in the file, and if you do add canonical structure,
say so in `## Notes`.

The one thing worth normalising is the **next-phase pointer**: a future session (or a
cron job) looks for that line to know where to start. If a legacy gatelog lacks it, add
it, because its absence is what makes "which phase is next?" ambiguous.

`tools/gatelog_check.py locate <dir>` reports which files were found, under their real
on-disk names, and whether the dialect is `canonical` or `legacy` — use it when you are
unsure, and `gatelog_check.py validate <dir>` to check the phase lists in the gatelog and
the plan actually agree.
