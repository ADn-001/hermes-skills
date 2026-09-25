# Ticket format

Written to `/home/user/codereview/<project-name>/tickets/<ticket-id>.md`. `<ticket-id>` format: `TICKET-<date>-<short-slug>` (e.g. `TICKET-2026-09-22-auth-webhook-hardening`).

A ticket is a cover summary plus the bundled ledger entries it groups — dev-sprint's "Starting fresh" step reads this whole file as its input spec.

```markdown
# Ticket: <short title>

ID: TICKET-2026-09-22-auth-webhook-hardening
Project: <project-name>
Created: 2026-09-22
Source: nightly-support (grouped from codebase-audit ledger)

## Summary
<2-4 sentences: what this ticket covers and why these findings were grouped
together — e.g. "both findings touch webhook signature validation in the
same module and are best fixed as one coherent change.">

## Bundled findings
<one block per finding included, copied verbatim from the ledger — same
fields, so nothing is lost in translation>

```yaml
id: CR-billing-service-0001
title: Stripe webhook handler skips signature verification on retry path
category: sec
severity: critical
location: src/webhooks/stripe.py:88
description: >
  ...
impact: >
  ...
suggested_fix: >
  ...
```

<... one per bundled finding ...>

## Notes for dev-sprint
<anything nightly-support noticed while grouping that plan.md's phases
should account for — e.g. "these two findings share a module; consider
one phase that touches both rather than two separate phases.">
```

Keep the bundled findings verbatim (don't paraphrase away detail dev-sprint's recon step will need) and keep the summary short — it's a pointer, not a replacement for the individual finding detail.
