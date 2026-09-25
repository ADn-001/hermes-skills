"""Fixture-driven tests for tools/ledger.py and tools/_blockyaml.py."""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _blockyaml as by  # noqa: E402
import ledger  # noqa: E402

HEADER = """# Codebase Audit Ledger — demo

Last run: 2026-09-23

Prose that must survive every rewrite, including a — dash and a `backtick`
and a line that mentions status: new in passing.
"""

ENTRY = '''
### CR-demo-0001 — First finding with an em dash in the prose heading

```yaml
id: CR-demo-0001
title: "First finding \\u2014 with a unicode escape and a quoted title"
category: security
severity: high
location: "app.py:10-20"
description: >-
  save() truncates the file before json.dump, so a concurrent reader sees a
  partial document. The window is real because the server is threaded.

  Second paragraph after a blank line.
impact: >-
  The whole store is silently discarded on the next start.
suggested_fix: |-
  Write to a temp file and os.replace() it.
covered_by_test: "No. Nothing exercises a partial write."
approved: false
status: new
first_seen: 2026-09-20
last_seen: 2026-09-23
linked_ticket: null
linked_cron_job: null
overlaps_active_phase: null
```
'''

ENTRY2 = '''
### CR-demo-0002 — Second finding

```yaml
id: CR-demo-0002
title: "Second finding"
category: tooling-gap
severity: low
location: "tools/x.py:1"
description: >-
  A folded description that runs
  over two lines.
impact: >-
  Low impact.
suggested_fix: >-
  Fix it.
covered_by_test: "Yes — test_x.TestA.test_b"
approved: true
status: resolved
first_seen: 2026-09-01
last_seen: 2026-09-02
linked_ticket: CR-DEMO-9
linked_cron_job: nightly-demo
overlaps_active_phase: null
```
'''

TRAILER = """
## Run summary

2 findings this run. Nothing was fixed.
"""


def read(path, mode="r"):
    """Read a file without leaking the handle (ResourceWarning hygiene)."""
    with open(path, mode, encoding=None if "b" in mode else "utf-8") as fh:
        return fh.read()


def entry(overrides=None, eid="CR-demo-0001", **kw):
    """Build a synthetic entry block with optional field overrides."""
    fields = {
        "id": eid,
        "title": f"Title for {eid}",
        "category": "security",
        "severity": "medium",
        "location": "app.py:1",
        "description": ">-",
        "impact": ">-",
        "suggested_fix": ">-",
        "covered_by_test": "No.",
        "approved": "false",
        "status": "new",
        "first_seen": "2026-09-20",
        "last_seen": "2026-09-20",
        "linked_ticket": "null",
        "linked_cron_job": "null",
        "overlaps_active_phase": "null",
    }
    fields.update(overrides or {})
    fields.update(kw)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items() if v is not None)
    return f"\n### {eid}\n\n```yaml\n{body}\n```\n"


def make_ledger(tmpdir, blocks, header=HEADER, trailer=TRAILER):
    path = os.path.join(tmpdir, "ledger.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + "".join(blocks) + trailer)
    return path


class BlockYamlTest(unittest.TestCase):
    def test_scalars(self):
        b = by.parse_block(
            'a: null\nb: ~\nc: true\nd: false\ne: 42\nf: -7\n'
            'g: 1.5\nh: plain text here\ni:\n')
        self.assertEqual(b.errors, [])
        self.assertIsNone(b.fields["a"])
        self.assertIsNone(b.fields["b"])
        self.assertIs(b.fields["c"], True)
        self.assertIs(b.fields["d"], False)
        self.assertEqual(b.fields["e"], 42)
        self.assertEqual(b.fields["f"], -7)
        self.assertEqual(b.fields["g"], 1.5)
        self.assertEqual(b.fields["h"], "plain text here")
        self.assertIsNone(b.fields["i"])

    def test_quoted_and_escapes(self):
        b = by.parse_block(
            't: "a \\u2014 dash"\ns: \'it\'\'s fine\'\n'
            'n: "line\\nbreak\\ttab"\n')
        self.assertEqual(b.errors, [])
        self.assertEqual(b.fields["t"], "a \u2014 dash")
        self.assertEqual(b.fields["s"], "it's fine")
        self.assertEqual(b.fields["n"], "line\nbreak\ttab")

    def test_folded_joins_and_literal_keeps_newlines(self):
        b = by.parse_block(
            "f: >-\n  one\n  two\n\n  three after blank\n"
            "g: |-\n  line A\n  line B\n")
        self.assertEqual(b.errors, [])
        self.assertEqual(b.fields["f"], "one two\nthree after blank")
        self.assertEqual(b.fields["g"], "line A\nline B")

    def test_inline_lists(self):
        b = by.parse_block('a: [x, y, "z, with comma"]\nb: []\n')
        self.assertEqual(b.errors, [])
        self.assertEqual(b.fields["a"], ["x", "y", "z, with comma"])
        self.assertEqual(b.fields["b"], [])

    def test_malformed_is_an_error_not_an_exception(self):
        for bad in ('k: "unterminated\n',
                    'k: [1, 2\n',
                    "k: &anchor\n",
                    "  stray indented line\n",
                    "not a key value pair at all\n",
                    'k: "bad \\q escape"\n'):
            b = by.parse_block(bad)
            self.assertTrue(b.errors, f"expected an error for {bad!r}")

    def test_duplicate_key_is_an_error(self):
        b = by.parse_block("a: 1\na: 2\n")
        self.assertTrue(any("duplicate" in e.message for e in b.errors))

    def test_render_scalar_round_trip(self):
        for v in (None, True, False, 3, "plain", "has: colon", "",
                  "unicode \u2014 dash", "null"):
            text = by.render_scalar(v)
            parsed = by.parse_scalar(text)
            self.assertEqual(parsed, v, msg=text)

    def test_spans_cover_block_scalars(self):
        b = by.parse_block("a: 1\nb: >-\n  x\n  y\nc: 3\n")
        self.assertEqual(b.spans["a"], (0, 0))
        self.assertEqual(b.spans["b"], (1, 3))
        self.assertEqual(b.spans["c"], (4, 4))


class ParseLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_returns_header_and_entries(self):
        path = make_ledger(self.tmp, [ENTRY, ENTRY2])
        text = read(path)
        header, entries = ledger.parse_ledger(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].id, "CR-demo-0001")
        self.assertEqual(entries[0].fields["severity"], "high")
        self.assertIs(entries[0].fields["approved"], False)
        self.assertEqual(entries[0].fields["title"],
                         "First finding \u2014 with a unicode escape and a "
                         "quoted title")
        self.assertIn("Second paragraph", entries[0].fields["description"])
        # header is every non-block line, in order
        self.assertTrue(any("Prose that must survive" in l for l in header))
        self.assertTrue(any("Run summary" in l for l in header))
        self.assertFalse(any("```" in l for l in header))
        # line numbers point at real 1-based lines
        lines = text.split("\n")
        self.assertEqual(lines[entries[0].start_line - 1].strip(), "```yaml")
        self.assertEqual(lines[entries[0].end_line - 1].strip(), "```")

    def test_unterminated_fence_raises_ledger_error(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.parse_ledger("intro\n```yaml\nid: CR-x-0001\n")

    def test_missing_file_is_ledger_error(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.load(os.path.join(self.tmp, "nope.md"))

    def test_directory_is_ledger_error(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.load(self.tmp)


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def validate_text(self, text):
        header, entries = ledger.parse_ledger(text)
        return ledger.validate(entries)

    def test_clean_ledger_has_no_problems(self):
        probs = self.validate_text(HEADER + ENTRY + ENTRY2 + TRAILER)
        self.assertEqual([str(p) for p in probs], [])

    def test_duplicate_id_is_rejected(self):
        dup = ENTRY2.replace("CR-demo-0002", "CR-demo-0001")
        probs = self.validate_text(HEADER + ENTRY + dup + TRAILER)
        msgs = [str(p) for p in probs]
        dups = [p for p in probs if "duplicate id" in str(p)]
        self.assertEqual(len(dups), 1, msgs)
        # the blame line is the second block's id line, not the first
        lines = (HEADER + ENTRY + dup + TRAILER).split("\n")
        self.assertTrue(lines[dups[0].line - 1].startswith("id: CR-demo-0001"))
        self.assertIn("first defined at line", str(dups[0]))

    def test_illegal_status_is_rejected(self):
        bad = entry({"status": "in-flight"})
        probs = self.validate_text(HEADER + bad + TRAILER)
        msgs = [str(p) for p in probs]
        self.assertTrue(any("status must be one of" in m for m in msgs), msgs)

    def test_last_seen_before_first_seen_is_rejected(self):
        bad = entry({"first_seen": "2026-09-20", "last_seen": "2026-09-01"})
        probs = self.validate_text(HEADER + bad + TRAILER)
        msgs = [str(p) for p in probs]
        self.assertTrue(any("earlier than first_seen" in m for m in msgs), msgs)

    def test_non_iso_date_is_rejected(self):
        bad = entry({"first_seen": "20/09/2026"})
        probs = self.validate_text(HEADER + bad + TRAILER)
        self.assertTrue(any("not an ISO" in str(p) for p in probs))

    def test_bad_id_shape_is_rejected(self):
        bad = entry(eid="CR-demo-1")
        probs = self.validate_text(HEADER + bad + TRAILER)
        self.assertTrue(any("CR-<project>-NNNN" in str(p) for p in probs))

    def test_bad_severity_and_approved_are_rejected(self):
        probs = self.validate_text(HEADER + entry({"severity": "spicy",
                                                   "approved": '"maybe"'}) + TRAILER)
        msgs = " ".join(str(p) for p in probs)
        self.assertIn("severity must be one of", msgs)
        self.assertIn("approved must be true or false", msgs)

    def test_missing_field_is_rejected(self):
        block = entry()
        block = block.replace("linked_ticket: null\n", "")
        probs = self.validate_text(HEADER + block + TRAILER)
        self.assertTrue(any("missing required field 'linked_ticket'" in str(p)
                            for p in probs))

    def test_malformed_yaml_is_a_validation_error_not_a_traceback(self):
        bad = "\n```yaml\nid: CR-demo-0001\nthis line is not a key\n```\n"
        probs = self.validate_text(HEADER + bad + TRAILER)
        self.assertTrue(any("YAML:" in str(p) for p in probs))
        # and through the CLI, which must exit 1 without a traceback
        path = make_ledger(self.tmp, [bad])
        rc = self.run_cli("validate", path)
        self.assertEqual(rc, 1)

    def run_cli(self, *argv):
        out = []
        old = sys.stdout
        sys.stdout = _Sink(out)
        try:
            return ledger.main(list(argv))
        finally:
            sys.stdout = old

    def test_cli_validate_exit_codes(self):
        good = make_ledger(self.tmp, [ENTRY])
        self.assertEqual(self.run_cli("validate", good), 0)
        bad = make_ledger(self.tmp, [entry({"status": "bogus"})])
        self.assertEqual(self.run_cli("validate", bad), 1)
        self.assertEqual(self.run_cli("validate", "/nonexistent/x.md"), 1)


class _Sink:
    def __init__(self, buf):
        self.buf = buf

    def write(self, s):
        self.buf.append(s)

    def flush(self):
        pass

    @property
    def text(self):
        return "".join(self.buf)


class QueryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = make_ledger(self.tmp, [ENTRY, ENTRY2])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def entries(self):
        return ledger.load(self.path)[1]

    def test_next_id_does_not_reuse_a_resolved_entry(self):
        # CR-demo-0002 is `resolved` but its number must still be counted
        self.assertEqual(ledger.next_id(self.entries()), "CR-demo-0003")

    def test_next_id_after_rejecting_the_highest(self):
        e = entry(eid="CR-demo-0009", status="rejected", severity="low")
        path = make_ledger(self.tmp, [ENTRY, ENTRY2, e])
        self.assertEqual(ledger.next_id(ledger.load(path)[1]), "CR-demo-0010")

    def test_next_id_honours_explicit_project(self):
        self.assertEqual(ledger.next_id(self.entries(), "other"),
                         "CR-other-0001")

    def test_next_id_on_empty_ledger(self):
        path = make_ledger(self.tmp, [])
        with self.assertRaises(ledger.LedgerError):
            ledger.next_id(ledger.load(path)[1], None)

    def test_stats(self):
        s = ledger.stats(self.entries())
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_status"]["new"], 1)
        self.assertEqual(s["by_status"]["resolved"], 1)
        self.assertEqual(s["by_severity"]["high"], 1)
        self.assertEqual(s["approved"], 1)
        self.assertEqual(s["not_approved"], 1)
        self.assertEqual(s["open_awaiting_approval"], 1)
        self.assertEqual(s["approved_not_ticketed"], 0)

    def test_approved_not_ticketed_counts_approved_live_entries(self):
        e = entry(eid="CR-demo-0003", approved="true", status="ticketed")
        path = make_ledger(self.tmp, [e])
        self.assertEqual(ledger.stats(ledger.load(path)[1])
                         ["approved_not_ticketed"], 0)
        e2 = entry(eid="CR-demo-0003", approved="true", status="assigned")
        path = make_ledger(self.tmp, [e2])
        self.assertEqual(ledger.stats(ledger.load(path)[1])
                         ["approved_not_ticketed"], 1)

    def test_filters(self):
        es = self.entries()
        self.assertEqual(len([e for e in es if ledger._matches(e, "new")]), 1)
        self.assertEqual(len([e for e in es if ledger._matches(e, approved=True)]), 1)
        self.assertEqual(len([e for e in es if ledger._matches(e, min_sev="high")]), 1)
        self.assertEqual(len([e for e in es if ledger._matches(e, min_sev="critical")]), 0)

    def test_read_only_subcommands_do_not_touch_the_file(self):
        before = os.stat(self.path)
        mtime = before.st_mtime
        data = read(self.path, "rb")
        ledger.stats(self.entries())
        ledger.next_id(self.entries())
        ledger.stale_assigned(self.entries(), 26, datetime(2026, 9, 23, 12, 0))
        ledger.validate(self.entries())
        after = os.stat(self.path)
        self.assertEqual(after.st_mtime, mtime)
        self.assertEqual(read(self.path, "rb"), data)


class StaleAssignedTest(unittest.TestCase):
    """The deadlock fix: `assigned` is never moved back, so detect it."""

    NOW = datetime(2026, 9, 25, 12, 0, 0)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stale_ids(self, *blocks, hours=26):
        path = make_ledger(self.tmp, list(blocks))
        stale, cronless, unknown = ledger.stale_assigned(
            ledger.load(path)[1], hours, self.NOW)
        return [s["id"] for s in stale], [c["id"] for c in cronless], unknown

    def test_flags_30_hour_old_assigned_and_not_2_hour_old(self):
        old = entry(eid="CR-demo-0001", status="assigned",
                    first_seen="2026-09-23", last_seen="2026-09-23")
        # self.NOW is 2026-09-25 12:00; a date-only last_seen means midnight
        # of that day -> 36h old, comfortably over 26h.
        fresh = entry(eid="CR-demo-0002", status="assigned",
                      first_seen="2026-09-25", last_seen="2026-09-25")
        stale, cronless, unknown = self.stale_ids(old, fresh)
        self.assertEqual(stale, ["CR-demo-0001"])
        self.assertEqual(cronless, [])
        self.assertEqual(unknown, [])

    def test_exact_30_hour_boundary_case(self):
        """30h old vs 2h old, measured with a full timestamp -- now ISO."""
        base = "2026-09-25"
        path = make_ledger(self.tmp, [
            "\n```yaml\nid: CR-demo-0001\ntitle: t\ncategory: c\n"
            "severity: low\nlocation: l\ndescription: d\nimpact: i\n"
            "suggested_fix: s\ncovered_by_test: n\napproved: false\n"
            "status: assigned\nfirst_seen: 2026-09-01\n"
            "last_seen: 2026-09-24T06:00:00\nlinked_ticket: null\n"
            "linked_cron_job: null\noverlaps_active_phase: null\n```\n",
        ])
        entries = ledger.load(path)[1]
        # 2026-09-25 12:00 - 30h = 2026-09-24 06:00 -> stale (>= 26h)
        stale, _, _ = ledger.stale_assigned(entries, 26, self.NOW)
        self.assertEqual([s["id"] for s in stale], ["CR-demo-0001"])
        # 2h after last_seen -> not stale
        stale2, _, _ = ledger.stale_assigned(entries, 26,
                                             datetime(2026, 9, 24, 8, 0))
        self.assertEqual(stale2, [])

    def test_assigned_with_a_ticket_is_not_stale(self):
        ok = entry(eid="CR-demo-0001", status="assigned",
                   linked_ticket="CR-demo-77", last_seen="2026-01-01")
        stale, _, _ = self.stale_ids(ok)
        self.assertEqual(stale, [])

    def test_ticketed_without_cron_is_flagged(self):
        e = entry(eid="CR-demo-0001", status="ticketed", linked_ticket="T-1")
        stale, cronless, _ = self.stale_ids(e)
        self.assertEqual(stale, [])
        self.assertEqual(cronless, ["CR-demo-0001"])

    def test_missing_last_seen_is_unknown_not_stale(self):
        e = entry(eid="CR-demo-0001", status="assigned", last_seen=None)
        stale, _, unknown = self.stale_ids(e)
        self.assertEqual(stale, [])
        self.assertEqual(unknown, ["CR-demo-0001"])

    def test_new_and_resolved_are_ignored(self):
        blocks = [entry(eid="CR-demo-0001", status="new", last_seen="2020-01-01"),
                  entry(eid="CR-demo-0002", status="resolved",
                        last_seen="2020-01-01")]
        stale, cronless, _ = self.stale_ids(*blocks)
        self.assertEqual((stale, cronless), ([], []))

    def test_cli_reports_and_exit_codes(self):
        old = entry(eid="CR-demo-0001", status="assigned", last_seen="2020-01-01")
        path = make_ledger(self.tmp, [old])
        out = _Sink([])
        sys.stdout = out
        try:
            rc = ledger.main(["stale-assigned", path, "--now", "2026-09-25T12:00:00",
                              "--json"])
        finally:
            sys.stdout = sys.__stdout__
        self.assertEqual(rc, 1)
        import json
        data = json.loads(out.text)
        self.assertEqual([s["id"] for s in data["stale_assigned"]],
                         ["CR-demo-0001"])
        # a clean ledger exits 0
        clean = make_ledger(self.tmp, [ENTRY])
        out2 = _Sink([])
        sys.stdout = out2
        try:
            rc2 = ledger.main(["stale-assigned", clean])
        finally:
            sys.stdout = sys.__stdout__
        self.assertEqual(rc2, 0)

    def test_bad_now_is_a_usage_level_error_not_a_crash(self):
        path = make_ledger(self.tmp, [ENTRY])
        out, err = _Sink([]), _Sink([])
        so, se = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            rc = ledger.main(["stale-assigned", path, "--now", "not-a-date"])
        finally:
            sys.stdout, sys.stderr = so, se
        self.assertEqual(rc, 1)
        self.assertIn("ISO", err.text)


class RewriteTest(unittest.TestCase):
    """The rewriters must be surgical: everything else is byte-identical."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = make_ledger(self.tmp, [ENTRY, ENTRY2])
        self.original = read(self.path)
        self.header, self.entries = ledger.parse_ledger(self.original)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_mut(self, *argv):
        out, err = _Sink([]), _Sink([])
        so, se = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            rc = ledger.main(list(argv))
        finally:
            sys.stdout, sys.stderr = so, se
        return rc, out.text, err.text

    def test_set_status_preserves_everything_else_byte_for_byte(self):
        rc, _, err = self.run_mut("set-status", self.path, "--id", "CR-demo-0001",
                                  "--status", "ticketed", "--ticket", "CR-DEMO-9",
                                  "--cron", "nightly-demo",
                                  "--now", "2026-09-24")
        self.assertEqual(rc, 0, err)
        new = read(self.path)
        # every line that is not inside the mutated entry's block is identical
        _, old_es = ledger.parse_ledger(self.original)
        _, new_es = ledger.parse_ledger(new)
        old_o, old_c = old_es[0].fence_open, old_es[0].fence_close
        new_o, new_c = new_es[0].fence_open, new_es[0].fence_close
        old_before, old_after = self.original.split("\n")[:old_o], \
            self.original.split("\n")[old_c + 1:]
        new_before, new_after = new.split("\n")[:new_o], \
            new.split("\n")[new_c + 1:]
        self.assertEqual(new_before, old_before)
        self.assertEqual(new_after, old_after)
        # header prose and trailer survive verbatim
        self.assertIn("Prose that must survive every rewrite", new)
        self.assertIn("## Run summary", new)
        self.assertIn("2 findings this run. Nothing was fixed.", new)
        # the target entry changed only in the mutated fields
        _, entries = ledger.parse_ledger(new)
        e1 = entries[0].fields
        self.assertEqual(e1["status"], "ticketed")
        self.assertEqual(e1["linked_ticket"], "CR-DEMO-9")
        self.assertEqual(e1["linked_cron_job"], "nightly-demo")
        self.assertEqual(e1["last_seen"], "2026-09-24")
        self.assertIn("Second paragraph after a blank line.", e1["description"])
        self.assertEqual(entries[1].fields, self.entries[1].fields)
        # the folded description text is still verbatim in the file
        self.assertIn("  save() truncates the file before json.dump, so a "
                      "concurrent reader sees a", new)
        self.assertEqual(new.count("```yaml"), 2)
        # no temp files left behind
        self.assertEqual([f for f in os.listdir(self.tmp) if f.startswith(".ledger")], [])

    def test_set_status_without_flags_still_refreshes_last_seen(self):
        rc, _, _ = self.run_mut("set-status", self.path, "--id", "CR-demo-0002",
                                "--status", "assigned", "--now", "2026-09-25")
        self.assertEqual(rc, 0)
        _, entries = ledger.parse_ledger(read(self.path))
        self.assertEqual(entries[1].fields["linked_ticket"], "CR-DEMO-9")
        self.assertEqual(entries[1].fields["status"], "assigned")
        self.assertEqual(entries[1].fields["last_seen"], "2026-09-25")

    def test_retitle_preserves_everything_else(self):
        rc, _, err = self.run_mut("retitle", self.path, "--id", "CR-demo-0001",
                                  "--severity", "critical",
                                  "--category", "auth-bypass")
        self.assertEqual(rc, 0, err)
        new = read(self.path)
        _, entries = ledger.parse_ledger(new)
        self.assertEqual(entries[0].fields["severity"], "critical")
        self.assertEqual(entries[0].fields["category"], "auth-bypass")
        self.assertEqual(entries[1].fields, self.entries[1].fields)
        self.assertIn("Prose that must survive every rewrite", new)
        # still valid afterwards
        self.assertEqual(ledger.validate(entries), [])

    def test_retitle_can_add_a_missing_key(self):
        block = entry().replace("category: security\n", "")
        path = make_ledger(self.tmp, [block])
        rc, _, _ = self.run_mut("retitle", path, "--id", "CR-demo-0001",
                                "--category", "smells")
        self.assertEqual(rc, 0)
        _, entries = ledger.parse_ledger(read(path))
        self.assertEqual(entries[0].fields["category"], "smells")
        self.assertEqual(entries[0].fields["severity"], "medium")

    def test_rewrite_is_atomic_and_leaves_no_temp_file_on_success(self):
        before = set(os.listdir(self.tmp))
        self.run_mut("set-status", self.path, "--id", "CR-demo-0001",
                     "--status", "new")
        self.assertEqual(set(os.listdir(self.tmp)), before)

    def test_duplicate_target_id_aborts(self):
        # same id in two blocks: refuse rather than pick one
        dup = ENTRY.replace("CR-demo-0001", "CR-demo-0007").replace(
            "First finding", "Cloned finding")
        path = make_ledger(self.tmp, [ENTRY2, dup, ENTRY2.replace(
            "CR-demo-0002", "CR-demo-0007")])
        before = read(path)
        rc, _, err = self.run_mut("set-status", path, "--id", "CR-demo-0007",
                                  "--status", "resolved")
        self.assertEqual(rc, 1)
        self.assertIn("appears in 2 blocks", err)
        self.assertEqual(read(path), before)

    def test_unknown_id_aborts(self):
        before = read(self.path)
        rc, _, err = self.run_mut("set-status", self.path, "--id", "CR-demo-9999",
                                  "--status", "resolved")
        self.assertEqual(rc, 1)
        self.assertIn("no entry with id", err)
        self.assertEqual(read(self.path), before)

    def test_illegal_status_is_a_usage_error(self):
        rc = ledger.main(["set-status", self.path, "--id", "CR-demo-0001",
                          "--status", "bogus"])
        self.assertEqual(rc, 2)

    def test_mutated_ledger_still_validates(self):
        self.run_mut("set-status", self.path, "--id", "CR-demo-0001",
                     "--status", "ticketed", "--ticket", "T-1",
                     "--now", "2026-09-24")
        _, entries = ledger.parse_ledger(read(self.path))
        self.assertEqual(ledger.validate(entries), [])

    def test_stale_entry_can_be_unstuck_with_set_status(self):
        old = entry(eid="CR-demo-0001", status="assigned", last_seen="2020-01-01",
                    first_seen="2020-01-01")
        path = make_ledger(self.tmp, [old])
        self.run_mut("set-status", path, "--id", "CR-demo-0001",
                     "--status", "new", "--now", "2026-09-25")
        _, entries = ledger.parse_ledger(read(path))
        stale, _, _ = ledger.stale_assigned(entries, 26, datetime(2026, 9, 25, 12))
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
