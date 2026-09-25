# Cron / unattended session prompt template

Paste this as-is into a scheduled/cron-triggered job pointed at the project dir. Each call does exactly one phase, then stops. It's idempotent by construction — safe to call on a schedule indefinitely until all phases are done.

```
This is a long autonomous task with phases, originally scoped by a main session and carried out incrementally by repeated cron job calls.

Read gatelog.md (which phase is done, which is next), plan.md (the phase-by-phase plan), and report.md (the initial recon findings) in <PROJECT_DIR>. Take over and do whichever phase hasn't been completed yet, following the directives originally given for this task (dev-sprint workflow: implement the phase's tasks, write its e2e test suite, then loop testing/debugging until all green).

Do exactly one phase. Once that phase is all-green, update gatelog.md (status, next-phase pointer, and findings section) and stop — do not start the next phase.

Before doing anything else: a previous cron-job agent may have exited or stopped looping before finishing a phase, or may have forgotten to update the gatelog. So your first order of business is to check what test suites already exist, run them one by one plus the full regression suite, and use the results — not just the gatelog's claimed status — to determine what phase the codebase is actually in and whether the previous agent left anything broken. Correct the gatelog if it's stale, note why, then proceed from the true state.

If gatelog.md already says "All phases complete" when you read it, do not implement anything. Instead check the dev-sprint skill's "The completion-audit guard": if an audit has already run for this completion (the gatelog's Notes say so, or /home/user/codereview/<PROJECT_NAME>/ledger.md exists and its Last run date is on or after the completion date), do NOT run another audit — just log a short "nothing to do" entry to today's daily report and stop. Only if no audit has run yet does the completion step apply: trigger the one-shot codebase-audit, record in the gatelog's Notes that it ran (date, ledger path, finding count), and stop.

At the end of this call, regardless of outcome, append a short entry to today's daily report file per the daily-weekly-report skill's format.
```

Swap `<PROJECT_DIR>` (and `<PROJECT_NAME>`, the bare project name used in ledger paths) for the actual values. Nothing else needs to change between runs — the files on disk carry all the state.

---

## Provisioning: arm the job properly

**The single most common way these jobs underperform is being created with only
`--skill dev-sprint` and nothing else.** The job then runs a whole sprint with no
TDD, no debugging skill, no review pass and no code-inspection tooling loaded, and
discovers mid-phase that it needs them. Provision the job with the skills the work
actually requires:

```bash
hermes cron create <interval> "<prompt from the template above, <PROJECT_DIR> substituted>" \
    --name "dev-sprint:<project-name>" \
    --workdir <PROJECT_DIR> \
    --skill dev-sprint \
    --skill test-driven-development \
    --skill systematic-debugging \
    --skill codebase-inspection \
    --skill requesting-code-review
```

Why each one earns its place on a sprint job:

| Skill | Why it is attached |
|---|---|
| `dev-sprint` | the workflow itself — phases, gates, gatelog |
| `test-driven-development` | the phase gate *is* a test suite; TDD is how it gets written before the code |
| `systematic-debugging` | the Test/Debug Sprint loop, instead of guess-and-rerun |
| `codebase-inspection` | recon, and the independent review pass on any nontrivial diff |
| `requesting-code-review` | the pre-commit quality/security gate on the phase's work |

Add situational ones when the project calls for them: `simplify-code` (a phase that turned
up needless complexity), `spike` (a genuinely unknown design question), `github` /
`github-push-pr` (git-based projects that land work as a PR), `hermes-agent` and the other
Hermes-infra skills **only** when the project under work *is* Hermes itself.

`--repeat` is deliberately **not** set: the job is meant to run on a schedule until the
gatelog says "All phases complete", at which point it finds nothing to do. `--workdir`
matters as much as the skills — it is what tells the session which project it is in.

### Interval

Default **every 3 hours** (what `nightly-support` provisions). One phase per invocation
means the interval is the phase cadence: 3h suits a phase that takes an hour or two of
agent time. Faster for a small phase, much slower for a large one — a 30-minute interval
on a 3-hour phase just re-runs the verify-first step repeatedly.

### Delivery

These jobs normally run for their side effects on disk. Set `--deliver local` to keep run
state in `hermes cron list` without injecting every run's output into a chat channel. If
the user wants to hear about completions, point `--deliver` at a real messaging target
(`telegram`, `discord`, `whatsapp:<name>`, …) — a bare platform name fails if no home
channel is configured.
