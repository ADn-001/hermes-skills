"""Fixture-driven tests for tools/gatelog_check.py."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gatelog_check as gc  # noqa: E402

CANONICAL_PLAN = """# Plan — demo

## Phase 0: Recon
- [ ] look around

## Phase 1: Build
- [ ] write it

## Phase 2: Verify
- [ ] run the suite
"""

CANONICAL_GATELOG = """# Gatelog — demo

Next phase to work on: Phase 1: Build

## Phase 0: Recon
Status: done
Test suite: tests/test_recon.py

### Findings
- Found two dead imports and an unused fixture.

## Phase 1: Build
Status: in progress
Test suite: tests/test_build.py
(12 tests) plus the live gate

### Findings

## Phase 2: Verify
Status: not started
Test suite: n/a

### Findings
"""

LEGACY_PLAN = """# PLAN — legacy demo

## Phase 0 — Readiness rig
- [x] baseline

## Phase 1 — Provider
- [x] done
"""

LEGACY_GATELOG = """# GATELOG — legacy demo

Next phase to work on: **Phase 1 — Provider**

## Phase 0 — Readiness rig
Status: **DONE**
Plan ref: `PLAN.md` Phase 0

- [x] baseline confirmed.

### info to know (Phase 0)
- jsdom lacks a real `fetch`; both must be stubbed.

## Phase 1 — Provider
Status: not started
Test suite: `tests/frontend/phase1.test.js`

### Findings
"""


def write(tmpdir, name, text):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def make_project(tmpdir, gatelog=CANONICAL_GATELOG, plan=CANONICAL_PLAN,
                 report=None, plan_name="plan.md", gatelog_name="gatelog.md",
                 report_name="report.md"):
    d = tempfile.mkdtemp(dir=tmpdir)
    if plan is not None:
        write(d, plan_name, plan)
    write(d, gatelog_name, gatelog)
    if report is not None:
        write(d, report_name, report)
    return d


class _Sink:
    def __init__(self):
        self.buf = []

    def write(self, s):
        self.buf.append(s)

    def flush(self):
        pass

    @property
    def text(self):
        return "".join(self.buf)


class LocateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_locate_finds_PLAN_md_and_reports_legacy(self):
        """The case-sensitivity bug: dev-sprint missed uppercase PLAN.md."""
        d = make_project(self.tmp, gatelog=LEGACY_GATELOG, plan=LEGACY_PLAN,
                         report="# report\n", plan_name="PLAN.md",
                         report_name="REPORT.md")
        loc = gc.locate(d)
        self.assertEqual(loc["dialect"], "legacy")
        self.assertEqual(loc["files"]["plan"], "PLAN.md")
        self.assertEqual(loc["files"]["gatelog"], "gatelog.md")
        self.assertEqual(loc["files"]["report"], "REPORT.md")
        self.assertEqual(loc["missing"], [])
        self.assertTrue(any("PLAN.md" in r for r in loc["legacy_reasons"]))
        self.assertTrue(any("info to know" in r for r in loc["legacy_reasons"]))

    def test_locate_canonical(self):
        d = make_project(self.tmp, report="# report\n")
        loc = gc.locate(d)
        self.assertEqual(loc["dialect"], "canonical")
        self.assertEqual(loc["legacy_reasons"], [])
        self.assertEqual(loc["missing"], [])
        self.assertTrue(loc["has_gatelog"])

    def test_locate_mixed_case_everywhere(self):
        d = make_project(self.tmp, plan_name="Plan.MD",
                         gatelog_name="GATELOG.md", report_name="Report.MD",
                         report="# r\n")
        loc = gc.locate(d)
        self.assertEqual(loc["files"]["plan"], "Plan.MD")
        self.assertEqual(loc["files"]["gatelog"], "GATELOG.md")
        self.assertEqual(loc["files"]["report"], "Report.MD")
        self.assertTrue(loc["has_gatelog"])

    def test_locate_reports_missing_optional_report(self):
        d = make_project(self.tmp)
        loc = gc.locate(d)
        self.assertIsNone(loc["files"]["report"])
        self.assertEqual(loc["missing"], ["report.md"])
        self.assertTrue(loc["has_gatelog"])

    def test_locate_on_missing_gatelog(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        write(d, "plan.md", CANONICAL_PLAN)
        loc = gc.locate(d)
        self.assertFalse(loc["has_gatelog"])
        self.assertIn("gatelog.md", loc["missing"])

    def test_locate_on_missing_dir_is_an_error_not_a_crash(self):
        with self.assertRaises(gc.GatelogError):
            gc.locate(os.path.join(self.tmp, "nope"))

    def test_cli_locate_exit_codes(self):
        d = make_project(self.tmp, plan_name="PLAN.md", plan=LEGACY_PLAN,
                         gatelog=LEGACY_GATELOG)
        self.assertEqual(self.run_cli("locate", d), 0)
        empty = tempfile.mkdtemp(dir=self.tmp)
        self.assertEqual(self.run_cli("locate", empty), 1)

    def run_cli(self, *argv):
        out = _Sink()
        so = sys.stdout
        sys.stdout = out
        try:
            rc = gc.main(list(argv))
        finally:
            sys.stdout = so
        return rc


class ParseGatelogTest(unittest.TestCase):
    def test_canonical_dialect(self):
        phases, pointer, pline = gc.parse_gatelog(CANONICAL_GATELOG)
        self.assertEqual([p.number for p in phases], [0, 1, 2])
        self.assertEqual([p.name for p in phases], ["Recon", "Build", "Verify"])
        self.assertEqual([p.status for p in phases],
                         ["done", "in progress", "not started"])
        self.assertEqual(phases[0].test_suite, "tests/test_recon.py")
        # a wrapped Test suite line is joined
        self.assertIn("12 tests", phases[1].test_suite)
        self.assertEqual(pointer, "Phase 1: Build")
        self.assertEqual(pline, 3)
        self.assertIn("dead imports", phases[0].findings)
        self.assertEqual(phases[1].findings.strip(), "")

    def test_legacy_dialect(self):
        phases, pointer, _ = gc.parse_gatelog(LEGACY_GATELOG)
        self.assertEqual([p.number for p in phases], [0, 1])
        self.assertEqual([p.name for p in phases],
                         ["Readiness rig", "Provider"])
        self.assertEqual([p.status for p in phases], ["done", "not started"])
        self.assertEqual(pointer, "Phase 1 — Provider")
        self.assertIn("jsdom", phases[0].findings)

    def test_status_with_trailing_prose(self):
        text = ("## Phase 0: A\nStatus: done (one caveat: unconfirmed)\n"
                "### Findings\n- x\n")
        phases, _, _ = gc.parse_gatelog(text)
        self.assertEqual(phases[0].status, "done")

    def test_non_phase_headings_are_ignored(self):
        text = CANONICAL_GATELOG + ("\n## Notes\nfree text\n\n"
                                    "## Post-gate pass — review\n"
                                    "Status: **NO OPEN PHASE — complete**\n")
        phases, _, _ = gc.parse_gatelog(text)
        self.assertEqual([p.number for p in phases], [0, 1, 2])

    def test_section_without_findings_heading(self):
        text = "## Phase 0: A\nStatus: not started\n- just a checklist\n"
        phases, _, _ = gc.parse_gatelog(text)
        self.assertEqual(len(phases), 1)
        self.assertIn("checklist", phases[0].findings)

    def test_missing_optional_test_suite(self):
        text = "## Phase 0: A\nStatus: not started\n"
        phases, _, _ = gc.parse_gatelog(text)
        self.assertEqual(phases[0].test_suite, "")

    def test_gatelog_with_no_phases(self):
        phases, pointer, _ = gc.parse_gatelog("# Gatelog\n\nnothing yet\n")
        self.assertEqual(phases, [])
        self.assertEqual(pointer, "")

    def test_plan_parsing_ignores_non_phase_headings(self):
        got = gc.parse_plan(CANONICAL_PLAN)
        self.assertEqual([n for n, _, _ in got], [0, 1, 2])
        got2 = gc.parse_plan(LEGACY_PLAN)
        self.assertEqual([n for n, _, _ in got2], [0, 1])


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, **kw):
        d = make_project(self.tmp, **kw)
        loc = gc.locate(d)
        return gc.validate_project(loc)

    def test_clean_canonical_project(self):
        errors, warns = self.check()
        self.assertEqual(errors, [])
        # phase 1 is in progress with an empty findings body -> no warning
        self.assertEqual(warns, [])

    def test_clean_legacy_project(self):
        errors, warns = self.check(gatelog=LEGACY_GATELOG, plan=LEGACY_PLAN,
                                   plan_name="PLAN.md")
        self.assertEqual(errors, [])
        # phase 1 is not started, so its empty body is not a warning
        self.assertEqual(warns, [])

    def test_missing_plan_is_an_error(self):
        errors, _ = self.check(plan=None)
        self.assertTrue(any("no plan.md" in e for e in errors), errors)

    def test_missing_gatelog_is_an_error(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        write(d, "plan.md", CANONICAL_PLAN)
        errors, _ = gc.validate_project(gc.locate(d))
        self.assertTrue(any("no gatelog.md" in e for e in errors), errors)

    def test_illegal_status_is_rejected(self):
        text = CANONICAL_GATELOG.replace("Status: in progress",
                                         "Status: sort of done")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("illegal status" in e for e in errors), errors)

    def test_missing_status_is_rejected(self):
        text = CANONICAL_GATELOG.replace("Status: not started\n", "")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("(no Status line)" in e for e in errors), errors)

    def test_two_in_progress_phases_is_rejected(self):
        text = CANONICAL_GATELOG.replace("Status: not started",
                                         "Status: in progress")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("at most one" in e for e in errors), errors)

    def test_pointer_disagreeing_with_reality_is_rejected(self):
        # says "All phases complete" while phase 1 is in progress
        text = CANONICAL_GATELOG.replace("Next phase to work on: Phase 1: Build",
                                         "Next phase to work on: All phases complete")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("All phases complete" in e for e in errors), errors)

    def test_pointer_naming_the_wrong_phase_is_rejected(self):
        text = CANONICAL_GATELOG.replace("Next phase to work on: Phase 1: Build",
                                         "Next phase to work on: Phase 2: Verify")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("first unfinished phase is 1" in e for e in errors),
                        errors)

    def test_missing_pointer_is_rejected(self):
        text = CANONICAL_GATELOG.replace(
            "Next phase to work on: Phase 1: Build", "no pointer here")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("pointer" in e for e in errors), errors)

    def test_pointer_agreeing_with_reality_is_clean(self):
        errors, _ = self.check()
        self.assertEqual(errors, [])

    def test_pointer_all_complete_when_all_done_is_clean(self):
        text = CANONICAL_GATELOG.replace("Status: in progress", "Status: done")
        text = text.replace("Status: not started", "Status: done")
        text = text.replace("Next phase to work on: Phase 1: Build",
                            "Next phase to work on: All phases complete (0-2)")
        errors, _ = self.check(gatelog=text)
        self.assertEqual(errors, [])

    def test_done_phase_with_empty_findings_is_a_warning_not_an_error(self):
        text = CANONICAL_GATELOG.replace(
            "## Phase 2: Verify\nStatus: not started", "## Phase 2: Verify\nStatus: done")
        errors, warns = self.check(gatelog=text)
        self.assertEqual(errors, [])
        self.assertTrue(any("Phase 2" in w and "empty" in w for w in warns),
                        warns)

    def test_phase_count_mismatch_is_rejected(self):
        plan = CANONICAL_PLAN.replace("## Phase 2: Verify\n- [ ] run the suite\n",
                                      "")
        errors, _ = self.check(plan=plan)
        self.assertTrue(any("does not mirror" in e for e in errors), errors)

    def test_phase_order_mismatch_is_rejected(self):
        plan = ("# Plan\n\n## Phase 1: Build\n\n## Phase 0: Recon\n\n"
                "## Phase 2: Verify\n")
        errors, _ = self.check(plan=plan)
        self.assertTrue(any("different order" in e for e in errors), errors)

    def test_extra_phase_in_gatelog_is_rejected(self):
        text = CANONICAL_GATELOG + ("\n## Phase 3: Extra\nStatus: not started\n"
                                    "### Findings\n")
        errors, _ = self.check(gatelog=text)
        self.assertTrue(any("only in gatelog: [3]" in e for e in errors), errors)

    def test_phase_name_drift_is_a_warning_not_an_error(self):
        plan = CANONICAL_PLAN.replace("## Phase 1: Build",
                                      "## Phase 1: Deploy to hardware")
        errors, warns = self.check(plan=plan)
        self.assertEqual(errors, [])
        self.assertTrue(any("gatelog calls it" in w for w in warns), warns)

    def test_gatelog_with_no_phase_sections(self):
        errors, _ = self.check(gatelog="# Gatelog\n\nempty\n")
        self.assertTrue(any("no '## Phase N'" in e for e in errors), errors)

    def test_cli_validate_exit_codes_and_json(self):
        d = make_project(self.tmp)
        out = _Sink()
        so = sys.stdout
        sys.stdout = out
        try:
            rc = gc.main(["validate", d, "--json"])
        finally:
            sys.stdout = so
        self.assertEqual(rc, 0)
        data = json.loads(out.text)
        self.assertTrue(data["ok"])
        self.assertEqual(data["error_count"], 0)

        bad = make_project(self.tmp, plan=None)
        out2 = _Sink()
        sys.stdout = out2
        try:
            rc2 = gc.main(["validate", bad])
        finally:
            sys.stdout = so
        self.assertEqual(rc2, 1)


class NextAndStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, **kw):
        d = make_project(self.tmp, **kw)
        return gc._load_project(d)

    def test_next_returns_first_unfinished(self):
        _, phases, _ = self.load()
        nxt = gc.next_phase(phases)
        self.assertEqual(nxt.number, 1)
        self.assertEqual(nxt.as_dict()["status"], "in progress")
        self.assertIn("test_build", nxt.as_dict()["test_suite"])

    def test_next_skips_done_phases(self):
        _, phases, _ = self.load(gatelog=LEGACY_GATELOG, plan=LEGACY_PLAN,
                                 plan_name="PLAN.md")
        self.assertEqual(gc.next_phase(phases).number, 1)

    def test_next_when_all_done(self):
        text = CANONICAL_GATELOG.replace("Status: in progress", "Status: done")
        text = text.replace("Status: not started", "Status: done")
        _, phases, _ = self.load(gatelog=text)
        self.assertIsNone(gc.next_phase(phases))

    def test_cli_next_json_shapes(self):
        d = make_project(self.tmp)
        out = _Sink()
        so = sys.stdout
        sys.stdout = out
        try:
            rc = gc.main(["next", d, "--json"])
        finally:
            sys.stdout = so
        self.assertEqual(rc, 0)
        data = json.loads(out.text)
        self.assertEqual(data["phase"], 1)
        self.assertEqual(data["name"], "Build")
        self.assertFalse(data["complete"])

        text = CANONICAL_GATELOG.replace("Status: in progress", "Status: done")
        text = text.replace("Status: not started", "Status: done")
        d2 = make_project(self.tmp, gatelog=text)
        out2 = _Sink()
        sys.stdout = out2
        try:
            gc.main(["next", d2, "--json"])
        finally:
            sys.stdout = so
        data2 = json.loads(out2.text)
        self.assertIsNone(data2["phase"])
        self.assertTrue(data2["complete"])

    def test_summary_counts(self):
        loc, phases, pointer = self.load()
        s = gc.summary(phases, loc, pointer)
        self.assertEqual(s["phases"], 3)
        self.assertEqual(s["done"], 1)
        self.assertEqual(s["counts"]["in progress"], 1)
        self.assertEqual(s["counts"]["not started"], 1)
        self.assertFalse(s["complete"])
        self.assertEqual(s["dialect"], "canonical")

    def test_cli_status(self):
        d = make_project(self.tmp)
        out = _Sink()
        so = sys.stdout
        sys.stdout = out
        try:
            rc = gc.main(["status", d, "--json"])
        finally:
            sys.stdout = so
        self.assertEqual(rc, 0)
        data = json.loads(out.text)
        self.assertEqual(data["phases"], 3)
        self.assertEqual(data["next"]["phase"], 1)

    def test_missing_gatelog_cli_is_exit_1_with_message(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        err = _Sink()
        so, se = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Sink(), err
        try:
            rc = gc.main(["status", d])
        finally:
            sys.stdout, sys.stderr = so, se
        self.assertEqual(rc, 1)
        self.assertIn("no gatelog.md", err.text)


class ReadOnlyTest(unittest.TestCase):
    def test_no_subcommand_writes_to_the_project(self):
        tmp = tempfile.mkdtemp()
        try:
            d = make_project(tmp, gatelog=LEGACY_GATELOG, plan=LEGACY_PLAN,
                             plan_name="PLAN.md", report_name="REPORT.md",
                             report="# r\n")
            before = {}
            for name in sorted(os.listdir(d)):
                with open(os.path.join(d, name), "rb") as fh:
                    before[name] = (os.stat(os.path.join(d, name)).st_mtime, fh.read())
            for cmd in ("locate", "validate", "next", "status"):
                for extra in ([], ["--json"]):
                    so = sys.stdout
                    sys.stdout = _Sink()
                    try:
                        gc.main([cmd, d] + extra)
                    finally:
                        sys.stdout = so
            after = sorted(os.listdir(d))
            self.assertEqual(after, sorted(before))
            for name in after:
                with open(os.path.join(d, name), "rb") as fh:
                    self.assertEqual(
                        (os.stat(os.path.join(d, name)).st_mtime, fh.read()),
                        before[name], name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
