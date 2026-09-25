# Agent delegation, skills, and tools

**The canonical version of this reference for the whole skill family lives in
`codebase-audit/references/agents-and-tools.md`. Read that one.**

This file used to be a second, shorter copy of the same table, and the two drifted apart
— which is the exact failure mode a shared reference is meant to prevent. A duplicated
reference gets maintained zero times and trusted twice. If you are updating the table,
edit the canonical file and change nothing here.

## Why it is shared and not per-skill

Every skill in this family (`dev-sprint`, `codebase-audit`, `nightly-support`,
`daily-weekly-report`) answers the same question: *which agent role, skill and tool
belongs to this subtask?* The answer does not depend on which skill is running, so
keeping one copy means an improvement made while auditing is immediately correct while
sprinting.

## The short version, for when you have not opened the canonical file

Delegate by default. A single agent grinding through recon, implementation, review,
testing, debugging and docs in one undifferentiated pass has no independent check on its
own blind spots, and burns context doing things a narrower agent would do faster and more
carefully. Spawn a subagent for any piece of work with a self-contained goal that does not
need the parent's full context — review, testing, debugging and auditing especially. In a
cron session with no human present this matters *more*, not less: there is nobody to catch
a phase that quietly went wrong.

The roles that come up most while running `dev-sprint`:

| Subtask | Reach for |
|---|---|
| writing a phase's code | `test-driven-development` — write the test with the code, not after |
| the phase's e2e/regression suite | `test-driven-development` |
| reviewing a nontrivial diff | `codebase-inspection`, `requesting-code-review` |
| recon, or understanding something unanticipated | `codebase-inspection`, `spike` |
| a failing test in the Test/Debug loop | `systematic-debugging`, `python-debugpy` (Python), `node-inspect-debugger` (Node) |
| landing work as a reviewable PR | `github`, `github-push-pr` |
| keeping a multi-step sprint on track | the `todo` tool |
| pinning down scope with a live human | `clarify` |

The canonical file has the full table with the "spawn an agent when…" column, the
reasoning behind each entry, the expanded pool, and the guidance on the
Hermes-infrastructure skills that apply only when the project being worked on *is* Hermes.

## Arming a cron job with these skills

The table above is not only for choosing subagents mid-session. When this skill provisions
a recurring dev-sprint cron, the same mapping decides what to attach to the job — a job
created with only `--skill dev-sprint` runs a whole sprint with no TDD, debugging or review
tooling loaded. See `references/cron-prompt.md` for the provisioning block and the exact
flags.
