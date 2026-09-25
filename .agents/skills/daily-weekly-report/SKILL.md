---
name: daily-weekly-report
description: Maintains a rolling daily activity log that any hermes session or cron job appends a short SIGNIFICANT entry to at the end of its task cycle, and turns that log into two pre-written report files (a daily and a weekly) that are regenerated on a schedule and read back deterministically when the user asks. Two trigger modes in one skill — "daily report" and "weekly report" — typically invoked via Alexa ("what happened today" / "give me my weekly report") through the alexa-hermes-bridge, where the answer is a file read rather than a fresh model run. Use this whenever the user asks what happened today, this week, for a status update/report, or when another skill needs to know where/how to log its own end-of-cycle entry. Log status and progress on codebases and assigned work, not routine background operations.
---

# Daily / Weekly Report

One skill, two trigger modes, because weekly literally just reads what daily already wrote —
no separate storage or format to keep in sync.

The design has two halves, and both matter:

1. **A raw daily log** that skills append to. Everything significant that happened.
2. **Two pre-written report files** — a daily and a weekly — regenerated on a schedule by
   cron jobs, and read back verbatim when the user asks.

Half 2 exists because answering "what happened today?" by re-reading the log and
summarising it on the spot is slow, costs a model call, and produces a different — usually
thinner — answer every time. Writing the report once, on a schedule, means the user gets
the same considered answer instantly, and the summarisation cost is paid once a day instead
of once per question.

## Where things live

- `/home/user/reports/daily/YYYY-MM-DD.md` — the raw daily log, one file per day.
- `/home/user/reports/daily-report.md` — the **current daily report**, rewritten in place
  each time the daily report job runs.
- `/home/user/reports/weekly-report.md` — the **current weekly report**, same deal.
- Rolling window of the **most recent 7 log files that exist**, not a calendar-week — if a
  day had no activity, there's no file for it, and that's fine; don't create empty files
  just to keep a fixed 7-day span. When any skill writes a new day's file, prune anything
  older than the 7 most recent.

The two report files are **overwritten, not appended** — each holds the state as of its
last run, and always names the window it covers. That is what makes them cheap to read:
a caller opens one file and knows exactly what it is getting.

## What is worth logging (read this before appending anything)

**The log is a status channel for codebases and assigned work. It is not an activity
heartbeat.** A day's log that lists every routine operation has buried the three lines the
user actually needed, and there is no way to get them back.

Log an entry when something **changed state that the user might want to know about**:

| Log it | Don't log it |
|---|---|
| a dev-sprint phase completed, or a phase's tests went green | a dev-sprint cron woke up and found nothing to do |
| a codebase-audit ran, and what it found | — |
| a finding was approved, ticketed, or resolved | — |
| a ticket was written and its dev-sprint cron provisioned | — |
| something failed, was blocked, or needs a human decision | — |
| a deliberate change to a project's scope, plan or config | — |
| a long-running job finished with a result worth reading | a routine poll, health check, or no-op sync |
| — | greetings, endpoint switches, "what's your IP", relinks |
| — | a skill run that merely started, or a reminder that fired as designed |
| — | per-request bridge/HTTP/media operations of any kind |

The test: **would the user be surprised to learn about this a week from now?** If the entry
describes something that is now different from how it was yesterday, in a project or a
task, it belongs. If it describes the system doing its job, it does not.

When a cycle does nothing but confirm that everything is already fine, it does not need an
entry at all. If you judge a "nothing happened" cycle is worth recording — genuinely rare —
keep it to a single line and fold it into any other entry for that project on the same day
rather than giving it its own heading.

## Writing an entry (used by every other skill in this family, and any other Hermes skill)

At the end of a task cycle, append a short entry — a few lines, not a transcript — to today's file (create it if it doesn't exist yet):

```markdown
# Daily Report — 2026-09-22

## <time>, <skill-name>
<what changed, the outcome, anything needing the user's attention — 1-4 lines>

## <time>, <skill-name>
...
```

Good entries:
```
## 14:32, dev-sprint
billing-service: phase 2 of 4 done, all green. Next is rate limiting.

## 02:00, nightly-support
Scope: billing-service, inventory-service. Ticketed
TICKET-2026-09-22-auth-webhook-hardening (billing-service, 2 findings,
critical+low); cron provisioned every 3h at :20.
inventory-service skipped — dev-sprint in flight.
```

Bad entry (too vague to be useful in a summary): `## nightly-support ran`.

Bad entry (true, but not worth a heading — it belongs nowhere near this log): `## 21:03,
greeting` / `greeting set from echo.`

**Watch the day boundary.** A cycle that starts before midnight and finishes after it belongs in
the *new* day's file (that is "today" when you write the entry), not the one the cycle started in.
Check the clock (`date`) right before appending if the run has been long, and verify where the
entry actually landed — the bridge's own `log_daily` writes to the current day too, so an entry
can end up in a different file than the rest of the run's entries if you guess the timestamp.

## The two report jobs (who writes the report files)

Two cron jobs own the report files. They are the only things that write them.

**Daily job** — runs shortly after the day it reports on is over (e.g. `10 0 * * *`, or
late evening before midnight if the user wants same-day). It reads the day's log file and
**overwrites** `/home/user/reports/daily-report.md`.

**Weekly job** — runs once a week (e.g. Monday morning). It reads the most recent 7 log
files and **overwrites** `/home/user/reports/weekly-report.md`.

Each report file is self-describing — it states the window it covers, so a reader never has
to guess whether they are looking at today or last Tuesday:

```markdown
# Daily report — 2026-09-25

## Status
- billing-service: phase 3 of 5 in progress. All 286 tests green.
- inventory-service: 2 findings approved, awaiting nightly-support.

## Needs you
- CR-inventory-0014 (high) still unapproved — it blocks the auth ticket.

## Done today
- Phase 2 landed: webhook signature verification.
```

The daily report favours **status and what needs a decision**; the weekly favours **themes
and outcomes** ("three phases landed across two projects, one ticket went out, one audit
still waiting on your approval") rather than a day-by-day recap. Both should name concrete
projects and ids — a report that says "several things happened" has failed.

Set the two jobs up with the `cronjob` tool. Each is a small, bounded job; attach this
skill to it so it uses these conventions. Keep them independent — a failing weekly job must
not stop the daily one.

## Trigger mode 1: daily report

On request ("what happened today," "give me the daily report"):

1. **Read `/home/user/reports/daily-report.md`.** That is the whole point of pre-writing it.
2. If that file doesn't exist or is stale (its stated date is older than the most recent
   log file), say so plainly, then fall back: read the newest log file, say which date it is
   from — never imply an older day is today — and summarise that.
3. **Do not run a model to produce the report.** Deliver the file's content, lightly
   adapted for the channel. Re-summarising a summary is how the detail gets lost.
4. Spoken channels (Alexa / `alexa-echo-channel`) get at most three short spoken sentences
   with no markdown, no headings, no file paths and no raw field names. The detail lives in
   the file; the voice answer is the headline and the one thing that needs the user.

## Trigger mode 2: weekly report

On request ("weekly report," "what happened this week"):

1. **Read `/home/user/reports/weekly-report.md`.** Same deterministic path as daily.
2. If it's missing or predates the newest log file, fall back to reading the up-to-7 most
   recent log files and rolling them up yourself, and say that you did.
3. Same delivery rules: the file is the answer; adapt for the channel, don't re-infer.

## For skill authors

If you're building or retrofitting a Hermes skill that runs as a cron job or completes a task
cycle unattended, it should log here — but only the significant part. This is the user's
window into background work on their codebases and assigned tasks; a log diluted with
routine operations stops serving that purpose entirely. When in doubt, ask "what changed?"
rather than "what ran?" See `dev-sprint`, `codebase-audit`, and `nightly-support` for examples
of what a good entry looks like for that kind of work.
