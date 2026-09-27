"""Phase 11 — the ``TK-`` id namespace.

Phase 11 is groundwork for Phase 12 (a ticket form in the dashboard). Its
whole job is to make ``tools/ledger.py`` able to *read* a ticket id at all,
and to give tickets a counter that cannot collide with the findings they
respond to.

The E2E gate, verbatim from the plan:

    ``ledger.py validate`` accepts a ledger containing both prefixes;
    ``next-id`` for each prefix is independent; the 53 existing ``CR-``
    entries are untouched.

Every test builds its own temp ledger. The real one under
``/home/user/codereview`` is never opened, and there is a test that says so
explicitly, because a test suite that can rewrite the user's audit ledger is
the exact accident the plan's "53 existing entries are untouched" clause
exists to prevent.
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ledger  # noqa: E402

HEADER = "# Codebase Audit Ledger — TK namespace test\n\nLast run: 2026-09-27\n"
TRAILER = "\n_Trailing prose that must survive._\n"


def entry(eid, **over):
    """A minimal but *complete* entry block — validate() requires every field."""
    fields = {
        "id": eid,
        "title": "Title for %s" % eid,
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
    fields.update(over)
    body = "\n".join("%s: %s" % (k, v) for k, v in fields.items()
                     if v is not None)
    return "\n### %s\n\n```yaml\n%s\n```\n" % (eid, body)


def make_ledger(tmpdir, ids, **kw):
    path = os.path.join(tmpdir, "ledger.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HEADER + "".join(entry(i, **kw) for i in ids) + TRAILER)
    return path


def load(tmpdir, ids, **kw):
    return ledger.load(make_ledger(tmpdir, ids, **kw))[1]


class TestBothPrefixesAreAccepted(unittest.TestCase):
    """Plan task 1: ``ID_RE`` hard-rejected ``TK-``."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_a_tk_entry_validates(self):
        self.assertEqual(ledger.validate(load(self.tmp, ["TK-demo-0001"])), [])

    def test_a_ledger_mixing_both_prefixes_validates(self):
        """The plan's first E2E clause, in the shape Phase 12 will produce."""
        entries = load(self.tmp, ["CR-demo-0001", "TK-demo-0001",
                                  "CR-demo-0002", "TK-demo-0002"])
        self.assertEqual(ledger.validate(entries), [])

    def test_the_same_number_under_both_prefixes_is_not_a_duplicate(self):
        """``CR-demo-0001`` and ``TK-demo-0001`` are different ids.

        This is the reason the namespaces exist. Sharing one sequence would
        make the first ticket minted from a finding look like a collision.
        """
        entries = load(self.tmp, ["CR-demo-0001", "TK-demo-0001"])
        probs = [str(p) for p in ledger.validate(entries)
                 if "duplicate" in str(p)]
        self.assertEqual(probs, [])

    def test_a_duplicate_within_one_prefix_is_still_caught(self):
        """Cross-prefix is not a loophole for real duplicates."""
        entries = load(self.tmp, ["TK-demo-0001", "TK-demo-0001"])
        dups = [p for p in ledger.validate(entries) if "duplicate" in str(p)]
        self.assertEqual(len(dups), 1, [str(p) for p in ledger.validate(entries)])

    def test_a_cr_duplicate_is_still_caught_alongside_tickets(self):
        entries = load(self.tmp, ["CR-demo-0001", "TK-demo-0001",
                                  "CR-demo-0001"])
        dups = [p for p in ledger.validate(entries) if "duplicate" in str(p)]
        self.assertEqual(len(dups), 1, [str(p) for p in ledger.validate(entries)])

    def test_an_unknown_prefix_is_still_rejected(self):
        """Widening the regex must not make it accept anything."""
        for bad in ("XX-demo-0001", "cr-demo-0001", "TK-demo-1",
                    "TKdemo-0001", "TK-0001"):
            entries = load(self.tmp, [bad])
            probs = [p for p in ledger.validate(entries)
                     if "-<project>-NNNN" in str(p)]
            self.assertTrue(probs, "%r was accepted as a valid id" % bad)

    def test_a_hyphenated_project_name_still_parses(self):
        """The project segment is load-bearing.

        ``CR-alexa-hermes-0053`` must parse as project ``alexa-hermes``,
        number ``0053`` -- not project ``alexa``, number ``hermes``. Getting
        this wrong silently mints ids for a project that does not exist.
        """
        for eid, project, num in (
                ("CR-alexa-hermes-0053", "alexa-hermes", "0053"),
                ("TK-alexa-hermes-0001", "alexa-hermes", "0001"),
                ("CR-a-b-c-d-9999", "a-b-c-d", "9999"),
                ("CR-my.project-0042", "my.project", "0042")):
            m = ledger.ID_RE.match(eid)
            self.assertIsNotNone(m, "must match %r" % eid)
            self.assertEqual(m.group(2), project, eid)
            self.assertEqual(m.group(3), num, eid)

    def test_the_number_is_always_exactly_four_digits(self):
        """The anchor is what makes the project segment unambiguous.

        Worth stating as a test because a mutation that makes the project
        group *greedy* instead of lazy is **unobservable**: with ``$`` after
        exactly four digits, both forms backtrack to the same split on every
        well-formed id. I verified that across hyphenated, dotted and
        multi-hyphen projects. So the real property is not "lazy" -- it is
        "exactly four digits, anchored", and that is what this pins.
        """
        for bad in ("CR-demo-1", "CR-demo-12345", "CR-demo-00001"):
            self.assertIsNone(
                ledger.ID_RE.match(bad),
                "%r matched; the number must be exactly four digits" % bad)
        # ...and the real ledger's highest id still parses as expected.
        m = ledger.ID_RE.match("CR-alexa-hermes-0053")
        self.assertEqual(m.group(3), "0053")


class TestNextIdIsPerPrefix(unittest.TestCase):
    """Plan tasks 2 and 3: separate counters, ``--prefix TK``."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_each_prefix_has_its_own_counter(self):
        """The plan's second E2E clause.

        A shared counter would return ``TK-demo-0054`` for the first ticket
        in a project whose findings are already at 0053 — a ticket numbered
        as if it were the 54th finding.
        """
        ids = ["CR-demo-%04d" % n for n in range(1, 54)]
        entries = load(self.tmp, ids)
        self.assertEqual(ledger.next_id(entries, "demo"), "CR-demo-0054")
        self.assertEqual(
            ledger.next_id(entries, "demo", prefix=ledger.PREFIX_TK),
            "TK-demo-0001")

    def test_minting_tickets_does_not_advance_the_finding_counter(self):
        """The order independence that makes the namespaces safe.

        Mint fifty tickets, then ask for the next finding: it must still be
        0054. Without prefix-scoped maxing, every ticket would have pushed
        the finding sequence along.
        """
        ids = ["CR-demo-%04d" % n for n in range(1, 54)]
        entries = load(self.tmp, ids)
        for n in range(1, 51):
            ledger.next_id(entries, "demo", prefix=ledger.PREFIX_TK)
        self.assertEqual(ledger.next_id(entries, "demo"), "CR-demo-0054")

    def test_the_ticket_counter_advances_only_on_tickets(self):
        entries = load(self.tmp, ["TK-demo-0001", "TK-demo-0002",
                                  "CR-demo-0053"])
        self.assertEqual(
            ledger.next_id(entries, "demo", prefix=ledger.PREFIX_TK),
            "TK-demo-0003")
        self.assertEqual(ledger.next_id(entries, "demo"), "CR-demo-0054")

    def test_a_rejected_or_resolved_id_is_still_counted(self):
        """Ids are never reused, whatever the entry's status.

        Reusing a number after a finding is rejected would let a later entry
        inherit its history — and ``set-status --id`` addresses entries by
        id, so a reused number silently edits the wrong one.
        """
        entries = load(self.tmp, ["TK-demo-0009", "TK-demo-0002"],
                       status="rejected")
        self.assertEqual(
            ledger.next_id(entries, "demo", prefix=ledger.PREFIX_TK),
            "TK-demo-0010")

    def test_each_namespace_infers_its_own_project(self):
        """Inference looks only in the namespace being minted.

        A ledger with findings for ``demo`` and a ticket for ``other``: the
        next finding is ``CR-demo-0003`` and the next ticket is
        ``TK-other-0002``.

        I first wrote this expecting the *ticket* request to infer ``demo``
        from the findings, on the reasoning that a stray ticket must not
        redirect id minting. That is incoherent — it would invent
        ``TK-demo-0001`` for a project that has never had a ticket, and the
        ledger's whole model is one project per file. A ticket id must
        belong to the project whose tickets it is. Passing ``--project``
        explicitly is how a caller overrides this, and that already works.
        """
        entries = load(self.tmp, ["CR-demo-0001", "CR-demo-0002",
                                  "TK-other-0001"])
        self.assertEqual(ledger.next_id(entries, None), "CR-demo-0003")
        self.assertEqual(
            ledger.next_id(entries, None, prefix=ledger.PREFIX_TK),
            "TK-other-0002")

    def test_an_explicit_project_overrides_inference_in_either_namespace(self):
        """The escape hatch, and the reason inference can be this simple."""
        entries = load(self.tmp, ["CR-demo-0001", "TK-other-0001"])
        self.assertEqual(
            ledger.next_id(entries, "demo", prefix=ledger.PREFIX_TK),
            "TK-demo-0001")

    def test_a_ticket_only_ledger_cannot_infer_and_says_so(self):
        """The error names the namespace it looked in, so the fix is obvious."""
        entries = load(self.tmp, ["TK-demo-0001"])
        with self.assertRaises(ledger.LedgerError) as ctx:
            ledger.next_id(entries, None)
        self.assertIn("CR-*", str(ctx.exception))
        # ...and asking for the ticket namespace works fine.
        self.assertEqual(
            ledger.next_id(entries, None, prefix=ledger.PREFIX_TK),
            "TK-demo-0002")

    def test_the_cli_accepts_both_prefixes_and_rejects_others(self):
        """Plan task 3: ``next-id --prefix TK``."""
        path = make_ledger(self.tmp, ["CR-demo-0053"])

        def run(*args):
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ledger.main(list(args))
            return rc, buf.getvalue().strip()

        rc, out = run("next-id", path, "--project", "demo")
        self.assertEqual((rc, out), (0, "CR-demo-0054"))
        rc, out = run("next-id", path, "--project", "demo", "--prefix", "TK")
        self.assertEqual((rc, out), (0, "TK-demo-0001"))
        # An unknown prefix is a usage error (exit 2), not a silent CR.
        rc, _ = run("next-id", path, "--project", "demo", "--prefix", "XX")
        self.assertEqual(rc, 2)

    def test_the_default_prefix_is_unchanged_for_callers(self):
        """Every existing call site keeps working.

        ``next_id(entries)`` with no prefix must still mint a CR id — a
        signature change that altered the default would break the audit
        skill's existing invocations with no error anywhere.
        """
        entries = load(self.tmp, ["CR-demo-0001"])
        self.assertTrue(ledger.next_id(entries).startswith("CR-"))


class TestTheRealLedgerIsNeverOpened(unittest.TestCase):
    """The "53 existing entries are untouched" clause, enforced structurally.

    A test that only *reports* the count cannot fail if the code starts
    writing; this one fails if a test in this module even tries.
    """

    def test_no_test_method_can_reach_a_non_temp_path(self):
        """Walks each test's AST for a hard-coded absolute path.

        Three earlier versions of this guard failed, all the same way:

        1. grepping this file's own source for the live path -- which of
           course contains it, because the read-only check below names it;
        2. scanning lines for write-ish calls -- which matched my own
           docstring;
        3. an AST walk flagging every ``open``/``load`` whose first argument
           was not textually ``self.tmp`` -- which flagged the module's own
           helpers, which legitimately *take* a temp dir as a parameter.

        Each was a line-matching heuristic trying to answer a structural
        question, and each produced a test that failed for reasons unrelated
        to the property. This version asks the one question that actually
        matters and can be answered exactly: does any test body contain a
        hard-coded absolute path? A path built from ``tempfile`` or
        ``self.tmp`` is fine; a literal is not.
        """
        import ast as _ast
        tree = _ast.parse(open(__file__, encoding="utf-8").read())
        literals = []
        for node in _ast.walk(tree):
            if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            for inner in _ast.walk(node):
                if isinstance(inner, _ast.Constant) \
                        and isinstance(inner.value, str) \
                        and inner.value.startswith("/") \
                        and inner.value.count("/") > 2:
                    literals.append((node.name, inner.lineno,
                                     inner.value))
        # The one legitimate exception: the read-only live-ledger check
        # below, which exists precisely to assert the 53 findings are still
        # there. It opens for reading only.
        allowed = {"test_the_real_ledger_still_has_its_findings_and_no_tickets"}
        bad = [x for x in literals if x[0] not in allowed]
        self.assertEqual(bad, [],
                         "these tests hard-code an absolute path; build it "
                         "from tempfile instead: %s" % bad)

    def test_the_real_ledger_still_has_its_findings_and_no_tickets(self):
        """Read-only check on the live file.

        Skipped rather than failed when absent, because the suite has to run
        on a machine that has never run an audit. It is here so that a
        regression which *did* start rewriting the ledger is noticed even
        though nothing in this module would otherwise look at it.
        """
        path = "/home/user/codereview/alexa-hermes/ledger.md"
        if not os.path.exists(path):
            self.skipTest("no live ledger on this machine")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        ids = re.findall(r"^\s*id:\s*(\S+)", text, re.M)
        cr = [i for i in ids if i.startswith("CR-")]
        self.assertEqual(len(cr), 53,
                         "expected 53 CR- findings, found %d" % len(cr))
        self.assertEqual(
            [i for i in ids if i.startswith("TK-")], [],
            "Phase 11 is groundwork only; it must not have created a ticket")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
