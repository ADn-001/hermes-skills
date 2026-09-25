# tools/ — validator CLIs

Two standalone, stdlib-only Python 3 CLIs. No pip, no venv, no third-party deps.
Both are importable *and* runnable; all logic is in module-level functions and
the `__main__` block is a thin argparse wrapper.

| file | what it does |
| --- | --- |
| `ledger.py` | validate / query / atomically rewrite a codebase-audit ledger |
| `gatelog_check.py` | locate, validate and query dev-sprint state files |
| `_blockyaml.py` | narrow YAML block reader shared by `ledger.py` |
| `tests/` | `unittest` suites, fixture-driven, all in a tempdir |

## Exit codes (both scripts)

| code | meaning |
| --- | --- |
| 0 | success / clean |
| 1 | a real problem was found (validation failure, stale entry, bad input) |
| 2 | usage error (argparse) |

Malformed input never produces a traceback: it is reported and exits 1. These
run unattended at 3am, and a traceback is a failed run.

Read-only subcommands (`validate`, `list`, `find`, `next-id`, `stats`,
`stale-assigned`, `locate`, `next`, `status`) never write, not even an mtime.
Only `set-status` and `retitle` mutate, and they rewrite atomically.

Every subcommand that emits structured data takes `--json`.

## ledger.py

A ledger is one markdown file of fenced ```yaml blocks, one per finding.

```bash
# check every block, field, id, status, date and severity
python3 tools/ledger.py validate /home/user/codereview/my-project/ledger.md
# -> OK — 53 entries, 0 problems                                   (exit 0)

python3 tools/ledger.py find ledger.md --approved --status new --json
# -> the exact set nightly-support consumes; bare --approved means true

python3 tools/ledger.py list ledger.md --status new --min-sev high
# -> one line per finding: id  severity  status  approved  title

python3 tools/ledger.py next-id ledger.md
# -> CR-my-project-0054   (max over ALL entries; ids are never reused)

python3 tools/ledger.py stats ledger.md
# -> counts by status/severity/approval, plus open_awaiting_approval
#    and approved_not_ticketed

# the assigned-deadlock detector
python3 tools/ledger.py stale-assigned ledger.md --older-than-hours 26 --json
# -> {"stale_assigned": [...], "ticketed_without_cron": [...], ...}

# mutations: atomic, surgical, every other byte preserved
python3 tools/ledger.py set-status ledger.md --id CR-x-0007 --status ticketed \
    --ticket CR-42 --cron nightly-x --now 2026-09-25
python3 tools/ledger.py retitle ledger.md --id CR-x-0007 \
    --severity critical --category auth-bypass
```

`stale-assigned` is deliberately conservative: an entry is flagged only when it
is `assigned` with no `linked_ticket` **and** its `last_seen` is provably older
than N hours (default 26). An unparseable `last_seen` is reported as
`unknown_last_seen`, never as stale. It also flags `ticketed` entries with no
`linked_cron_job`. Exit 1 when anything is stale.

`set-status` / `retitle` locate the entry's block by line range and rewrite only
the named fields — no YAML round-trip, so descriptions are not reflowed. If the
target id appears in more than one block the command aborts with exit 1 rather
than guessing.

`parse_ledger(text) -> (header_lines, [Entry])` is the export for tests;
`Entry` carries `.id`, `.fields`, `.start_line`, `.end_line`.

## gatelog_check.py

```bash
# the case-sensitivity fix: finds PLAN.md, reports the legacy dialect
python3 tools/gatelog_check.py locate /home/user/my-other-project
# -> my-other-project  dialect=legacy
#      plan.md      found   PLAN.md
#      gatelog.md   found   gatelog.md

python3 tools/gatelog_check.py validate /home/user/my-other-project --json
# -> {"ok": false, "errors": ["phase list does not mirror PLAN.md: ..."],
#     "warnings": [...]}

python3 tools/gatelog_check.py status /home/user/my-other-project
# -> my-other-project: 16 phases (legacy dialect) — 13 done, 0 in progress, ...
python3 tools/gatelog_check.py next /home/user/my-other-project
# -> Phase 13: Laya gates (F2) via the Node child  [not started]
```

`validate` checks that the gatelog's phases mirror the plan's exactly (same
count, order and numbers), that every `Status:` is legal, that at most one phase
is `in progress`, and that `Next phase to work on:` agrees with reality. A
`done` phase with an empty Findings body is a **warning**, not an error.
Phase-name drift between plan and gatelog is also a warning.

Two dialects are understood: `canonical` (`plan.md`, `### Findings`) and
`legacy` (`PLAN.md`, `### info to know`). Both are detected, neither crashes.

## Tests

```bash
cd /home/user/hermes-skills
python3 -m unittest discover -s tools/tests -v
```

90 tests, all fixture-driven against synthetic ledgers/gatelogs in a tempdir.
The real ledgers and gatelogs are only ever read.
