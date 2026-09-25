# Ledger schema

One ledger per project: `/home/user/codereview/<project-name>/ledger.md`. Hybrid format — a short human-readable header, then one entry per finding as a fenced YAML block. Markdown around each block is fine (a one-line prose summary above the block is encouraged), but the block itself must be parseable as-is: field names and value shapes below are fixed, not freewheeled. `category` and `severity` *values* are freewheeled by the reviewing agent — pick whatever label fits — but the *field itself* must be present.

## File header

```markdown
# Codebase Audit Ledger — <project-name>

Last run: <date of most recent audit>
Location: /home/user/codereview/<project-name>/ledger.md

## Findings
```

`Last run:` is the audit's own idempotency marker, and it is load-bearing beyond
bookkeeping. `dev-sprint`'s completion step triggers a one-shot audit when a project
reaches "All phases complete" — and a recurring dev-sprint cron keeps firing after that
point. `dev-sprint` uses this date to decide whether the completion audit has already
run (a ledger whose `Last run:` is on or after the completion date means it has), so a
recurring job will not launch a fresh full-codebase audit on every single invocation.

**So always update `Last run:` when you audit, and never move it backwards.** If a run
finds nothing new, that is still a run: bump the date. A ledger with a stale `Last run:`
will make `dev-sprint` believe the completion audit is still outstanding and fire it
again.

## Per-entry block

```yaml
id: CR-<project-name>-0007
title: <short, specific — not "bug in auth">
category: bug            # freewheel: bug | sec | smell | pitfall | gap | ... — free prose is fine
severity: high           # freewheel but conventionally: critical | high | medium | low
location: src/auth/session.py:142
description: >
  What's actually wrong, specifically enough that someone with no other
  context can find and understand it.
impact: >
  What breaks, or could break, and why it matters. This is the context
  nightly-support's ticket needs — write it for that consumer, not just
  for a human skimming.
suggested_fix: >
  A direction, not necessarily a full patch.
covered_by_test: >
  What tests already cover this behaviour, and — more usefully — what they
  do NOT cover. "No test exercises X" is the most valuable thing to record here.
approved: false          # the user flips this by hand. Default false, always.
status: new               # new | assigned | ticketed | resolved | rejected
first_seen: 2026-09-22
last_seen: 2026-09-22
linked_ticket: null        # filled in by nightly-support once ticketed
linked_cron_job: null       # filled in by nightly-support once a dev-sprint cron is provisioned
overlaps_active_phase: null  # set to a plan.md phase name/id if Step 2 found overlap with in-flight dev-sprint work
```

**`category` and `severity` are free prose, deliberately.** A real ledger uses
`category: concurrency / state corruption` and `category: prompt injection`, not a closed
enum — forcing a narrow vocabulary loses the specific thing that makes a finding
findable. `severity` does stay on the four-step scale, because a ticket's priority is
derived from it. Everything else in the block is fixed: do not rename, add or drop fields.

**`covered_by_test` is not optional.** It is the field that tells whoever picks up the
ticket whether they are writing the first test for this behaviour or extending one, and
— more importantly — it is where a real gap hides. A finding whose `covered_by_test`
says "no test exercises this" is usually the finding that most needs writing. Every entry
in the first live ledger carried it; it is in the schema because it earned its place.

**Validate rather than eyeball.** These blocks are hand-formatted YAML in a markdown file
and they drift. When this skill's `tools/ledger.py` is available, run it — it checks field
presence, id shape and uniqueness, legal status values, the date ordering, and severity:

```bash
python3 tools/ledger.py validate /home/user/codereview/<project>/ledger.md
python3 tools/ledger.py stats    /home/user/codereview/<project>/ledger.md
```

`ledger.py next-id` computes the next unused id and `stale-assigned` finds entries a
crashed run stranded in `assigned` — the two things that are easy to get wrong by hand.


## Status lifecycle

```
new  →  (user sets approved: true)  →  assigned  →  ticketed  →  resolved
                                                            ↳ rejected (user disapproves after the fact, or nightly-support judges out of scope)
```

- **new** — just found (or still open from a prior run), not yet approved.
- **assigned** — approved and `nightly-support` has claimed it for an upcoming ticket, but hasn't written the ticket yet (short-lived; mainly prevents two `nightly-support` runs from double-claiming the same entry in a race).
- **ticketed** — a ticket/spec exists (`linked_ticket` filled in) and a `dev-sprint` cron has been provisioned (`linked_cron_job` filled in).
- **resolved** — either the finding stopped appearing in a later audit (auto-resolved), or the `dev-sprint` cron tied to its ticket reached "all phases complete" and the follow-up one-shot audit confirmed it's gone.
- **rejected** — the user un-approved it, or it turned out to be out of scope / not worth fixing. Kept for history, never re-surfaced as new.

**`assigned` and `ticketed` are claims, and a claim can be abandoned.** `nightly-support`
sets `assigned` *before* it writes the ticket, precisely so two concurrent runs cannot
double-claim the same finding. But a run that dies in that window leaves the entry
`assigned` with no ticket and no cron — and since nothing else in this family ever moves
`assigned` back to `new`, the project then looks permanently busy and its approved
findings are never ticketed again. A silent, permanent deadlock.

So `assigned` must be treated as **expiring**, not as a state:

- An `assigned` entry with no `linked_ticket` that has not been touched for longer than
  a full day of cycles (26 hours at the default 3h cadence) is **stranded**, not in-flight.
  `nightly-support` should treat the project as clear and say so out loud in the daily
  report before re-claiming it. Detect it with `ledger.py stale-assigned`.
- A `ticketed` entry whose `linked_cron_job` is `null` is stranded the same way: the
  ticket exists but nothing was ever scheduled to implement it.
- Never re-claim an entry that a genuinely live cron owns. The threshold is deliberately
  generous so slow work is not mistaken for a crash.

This is why `assigned` is documented as "short-lived" rather than as a resting state: it
is a lock with a timeout, not a queue position.

## Merge rules on each run (idempotency)

1. Match candidate findings against existing entries by `location` + substance of `description`, not by exact text — wording may shift slightly between runs.
2. Matched, still present → update `last_seen`. Never touch `status`/`approved` if they're anything other than `new` (don't downgrade a `ticketed` entry back to `new` just because it's still there — it's still there because the fix isn't done yet).
3. Not matched, i.e. genuinely new → append with the next unused `CR-<project-name>-NNNN` ID for this project. IDs are never reused, even across resolved/rejected entries.
4. Existing entry, not found this run → set `status: resolved` and append a one-line note under it (`<!-- auto-resolved <date>: not observed this run -->`), unless it's currently `assigned` or `ticketed` — in that case leave it for the `dev-sprint`-completion → follow-up-audit path in the `nightly-support`/`codebase-audit` chain to close out properly, don't auto-resolve mid-flight work.

## Worked example (two entries)

```markdown
# Codebase Audit Ledger — billing-service

Last run: 2026-09-22
Location: /home/user/codereview/billing-service/ledger.md

## Findings

Unvalidated webhook signature check.
```yaml
id: CR-billing-service-0001
title: Stripe webhook handler skips signature verification on retry path
category: sec
severity: critical
location: src/webhooks/stripe.py:88
description: >
  The retry branch of handle_webhook() calls process_event() directly,
  bypassing the verify_signature() call that the primary path uses.
impact: >
  An attacker who knows a retryable event shape could forge webhook
  events and trigger billing state changes without a valid signature.
suggested_fix: >
  Move verify_signature() above the branch so both paths call it, or
  factor it into a decorator applied to handle_webhook() itself.
approved: false
status: new
first_seen: 2026-09-22
last_seen: 2026-09-22
linked_ticket: null
linked_cron_job: null
overlaps_active_phase: null
```

Dead code smell, low severity, already ticketed from a prior run.
```yaml
id: CR-billing-service-0002
title: Unused legacy currency-conversion table still loaded on startup
category: smell
severity: low
location: src/startup/loaders.py:41
description: >
  load_legacy_fx_table() runs on every boot but nothing references its
  return value anywhere in the codebase (checked via grep + call graph).
impact: >
  Wastes a few hundred ms of startup time and a stale network call;
  no correctness risk, but worth clearing out.
suggested_fix: >
  Remove the call and the underlying loader once confirmed truly unused.
approved: true
status: ticketed
first_seen: 2026-08-30
last_seen: 2026-09-22
linked_ticket: TICKET-2026-09-15-startup-cleanup
linked_cron_job: /home/user/billing-service-cleanup
overlaps_active_phase: null
```
```
