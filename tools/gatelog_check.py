#!/usr/bin/env python3
"""gatelog_check.py — locate, validate and query dev-sprint state files.

A dev-sprint project dir holds a plan + a gatelog (+ optional report). Two
dialects exist in the wild:

  canonical  `plan.md` / `report.md`, `## Phase N: name`, `### Findings`
  legacy     `PLAN.md` / `REPORT.md`, `## Phase N — name`, `### info to know`

`locate` exists because the resume check used to look for lowercase `plan.md`
only, so a project with `PLAN.md` and a 16-phase gatelog was misread as a fresh
start. Everything here is read-only; nothing in this file ever writes.

Exit codes: 0 clean, 1 a real problem, 2 usage error.

Usage:
    python3 tools/gatelog_check.py locate  <project-dir> [--json]
    python3 tools/gatelog_check.py validate <project-dir> [--json]
    python3 tools/gatelog_check.py next    <project-dir> [--json]
    python3 tools/gatelog_check.py status  <project-dir> [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

STATE_FILES = ("plan", "gatelog", "report")
LEGAL_STATUSES = ("not started", "in progress", "done")
DONE_STATES = ("done",)

_PHASE_RE = re.compile(r"^##\s*Phase\s+(\d+)\s*[:—–-]?\s*(.*)$", re.I)
_STATUS_RE = re.compile(r"^Status\s*:\s*(.*)$", re.I)
_TESTSUITE_RE = re.compile(r"^Test suite\s*:\s*(.*)$", re.I)
_POINTER_RE = re.compile(r"^Next phase to work on\s*:\s*(.*)$", re.I)
_FINDINGS_RE = re.compile(r"^###\s*(findings|info to know)\b", re.I)
_HEADING_RE = re.compile(r"^#{1,6}\s")


class GatelogError(Exception):
    """Fatal but reportable; the CLI turns it into exit 1, never a traceback."""


class Phase:
    __slots__ = ("number", "name", "status", "test_suite", "line",
                 "findings_heading", "findings")

    def __init__(self, number, name, status, test_suite, line,
                 findings_heading, findings):
        self.number = number
        self.name = name
        self.status = status
        self.test_suite = test_suite
        self.line = line
        self.findings_heading = findings_heading
        self.findings = findings

    def as_dict(self):
        return {"phase": self.number, "name": self.name, "status": self.status,
                "test_suite": self.test_suite, "line": self.line}


def _clean(s):
    """Strip markdown emphasis/backticks and collapse whitespace."""
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", s)
    s = s.replace("`", "")
    return re.sub(r"\s+", " ", s).strip().strip(".,;:")


def _is_continuation(line):
    """A wrapped continuation of the previous `Test suite:` value.

    Wrapped test-suite lines are indented or otherwise start mid-sentence; a
    blank line, a list item, or an indented block that looks like real prose
    (indented bullets) ends the value.
    """
    if not line.strip():
        return False
    if re.match(r"^\s*([-*+]|\d+[.)])\s", line):
        return False
    return True


def normalize_status(raw):
    """`done` / `**DONE**` / `In Progress` -> canonical form, or '' if unknown.

    Real gatelogs append prose to the status (`Status: done (one caveat: ...)`),
    so a leading legal status word is enough; anything else is reported as
    unknown rather than guessed at.
    """
    s = _clean(raw).lower()
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    for legal in LEGAL_STATUSES:
        if re.match(re.escape(legal) + r"\b", s):
            return legal
    aliases = {"complete": "done", "completed": "done", "finished": "done",
               "notstarted": "not started", "inprogress": "in progress",
               "pending": "not started", "wip": "in progress"}
    first = s.split(" ", 1)[0].strip("([:")
    return aliases.get(first, "")


# --------------------------------------------------------------------------- #
# locate
# --------------------------------------------------------------------------- #
def locate(project_dir):
    """Find the state files case-insensitively. Never raises for a missing file."""
    if not os.path.isdir(project_dir):
        raise GatelogError(f"not a directory: {project_dir}")
    try:
        listing = os.listdir(project_dir)
    except OSError as exc:
        raise GatelogError(f"cannot list {project_dir}: {exc}") from exc
    by_lower = {}
    for name in listing:
        by_lower.setdefault(name.lower(), []).append(name)

    found, missing, names = {}, [], {}
    for key in STATE_FILES:
        target = f"{key}.md"
        hits = by_lower.get(target, [])
        names[key] = hits[0] if hits else None
        if hits:
            found[key] = os.path.join(project_dir, hits[0])
        else:
            missing.append(target)

    legacy_reasons = []
    if names["plan"] and names["plan"] != "plan.md":
        legacy_reasons.append(f"plan file is named {names['plan']!r}")
    if names["report"] and names["report"] != "report.md":
        legacy_reasons.append(f"report file is named {names['report']!r}")
    gatelog_path = found.get("gatelog")
    gatelog_text = ""
    if gatelog_path:
        for i, line in enumerate(_read(gatelog_path).split("\n"), 1):
            if re.match(r"^###\s*info to know\b", line, re.I):
                legacy_reasons.append(f"'### info to know' heading at line {i}")
                break
    dialect = "legacy" if legacy_reasons else "canonical"
    return {
        "project_dir": project_dir,
        "files": names,
        "found": sorted(found),
        "missing": missing,
        "dialect": dialect,
        "legacy_reasons": legacy_reasons,
        "has_gatelog": gatelog_path is not None,
    }


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise GatelogError(f"cannot read {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise GatelogError(f"{path} is not valid UTF-8: {exc}") from exc


# --------------------------------------------------------------------------- #
# gatelog parsing
# --------------------------------------------------------------------------- #
def parse_gatelog(text):
    """Return (phases, pointer_text, pointer_line). Never raises."""
    lines = text.split("\n")
    phases, pointer, pointer_line = [], "", 0
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip("\r")
        pm = _PHASE_RE.match(line)
        if pm:
            number = int(pm.group(1))
            name = _clean(pm.group(2))
            start = i
            i += 1
            status_raw, test_suite = "", ""
            body_lines, heading = [], ""
            pending_suite = None
            while i < n:
                body = lines[i].rstrip("\r")
                if _HEADING_RE.match(body):
                    if _FINDINGS_RE.match(body):
                        # the findings heading opens the body; the rest of the
                        # section is free text
                        heading = _clean(body.lstrip("#").strip())
                        i += 1
                        while i < n and not _HEADING_RE.match(lines[i].rstrip("\r")):
                            body_lines.append(lines[i])
                            i += 1
                    break
                sm = _STATUS_RE.match(body)
                tm = _TESTSUITE_RE.match(body)
                if sm:
                    status_raw = sm.group(1)
                    pending_suite = None
                    i += 1
                    continue
                if tm:
                    pending_suite = [tm.group(1)]
                    i += 1
                    continue
                if pending_suite is not None and _is_continuation(body):
                    # a wrapped `Test suite:` line: keep consuming, but stop at
                    # the first blank line or list item so prose is not eaten
                    pending_suite.append(body)
                    i += 1
                    continue
                if pending_suite is not None:
                    test_suite = _clean(" ".join(pending_suite))
                    pending_suite = None
                body_lines.append(lines[i])
                i += 1
            if pending_suite is not None:
                test_suite = _clean(" ".join(pending_suite))
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            phases.append(Phase(number, name, normalize_status(status_raw),
                                test_suite, start + 1, heading,
                                "\n".join(body_lines)))
            continue
        ptr = _POINTER_RE.match(line)
        if ptr and not pointer:
            pointer = _clean(ptr.group(1))
            pointer_line = i + 1
        i += 1
    return phases, pointer, pointer_line


def parse_plan(text):
    """Phase numbers (and names) declared by a plan file, in document order."""
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        m = _PHASE_RE.match(line.rstrip("\r"))
        if m:
            out.append((int(m.group(1)), _clean(m.group(2)), i))
    return out


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def validate_project(loc, warn=None):
    """Return (errors, warnings) as lists of readable strings."""
    warn = warn if warn is not None else []
    errors = []
    if not loc["has_gatelog"]:
        errors.append("no gatelog.md (case-insensitive) in this directory")
        return errors, warn
    gatelog_text = _read(loc["files"]["gatelog"] and
                         os.path.join(loc["project_dir"], loc["files"]["gatelog"]))
    phases, pointer, pointer_line = parse_gatelog(gatelog_text)
    if not phases:
        errors.append("gatelog contains no '## Phase N' sections")

    for p in phases:
        if p.status not in LEGAL_STATUSES:
            raw = p.status or "(no Status line)"
            errors.append(f"line {p.line}: Phase {p.number} ({p.name!r}) has an "
                          f"illegal status {raw!r}; expected one of "
                          f"{'|'.join(LEGAL_STATUSES)}")

    in_progress = [p for p in phases if p.status == "in progress"]
    if len(in_progress) > 1:
        nums = ", ".join(str(p.number) for p in in_progress)
        errors.append(f"{len(in_progress)} phases are 'in progress' ({nums}); "
                      f"at most one is allowed")

    if not pointer:
        errors.append("no 'Next phase to work on:' pointer line")
    elif pointer_line:
        low = pointer.lower()
        unfinished = [p for p in phases
                      if p.status in ("not started", "in progress", "")]
        if low.startswith("all phases complete"):
            if unfinished:
                nums = ", ".join(f"{p.number}({p.status or 'no status'})"
                                 for p in unfinished)
                errors.append(f"line {pointer_line}: pointer says 'All phases "
                              f"complete' but unfinished phases exist: {nums}")
        else:
            m = re.search(r"phase\s+(\d+)", low)
            if not m:
                errors.append(f"line {pointer_line}: pointer does not name a "
                              f"phase or 'All phases complete': {pointer!r}")
            else:
                want = int(m.group(1))
                first = unfinished[0] if unfinished else None
                if first is None:
                    errors.append(f"line {pointer_line}: pointer names Phase {want} "
                                  f"but every phase is done")
                elif first.number != want:
                    errors.append(f"line {pointer_line}: pointer names Phase "
                                  f"{want} but the first unfinished phase is "
                                  f"{first.number} ({first.status or 'no status'})")

    # plan <-> gatelog mirror
    if not loc["files"]["plan"]:
        errors.append("gatelog.md exists but no plan.md/PLAN.md alongside it")
    else:
        plan_path = os.path.join(loc["project_dir"], loc["files"]["plan"])
        plan = parse_plan(_read(plan_path))
        pnums = [n for n, _, _ in plan]
        gnums = [p.number for p in phases]
        if pnums != gnums:
            only_plan = [n for n in pnums if n not in gnums]
            only_log = [n for n in gnums if n not in pnums]
            detail = []
            if only_plan:
                detail.append(f"only in plan: {only_plan}")
            if only_log:
                detail.append(f"only in gatelog: {only_log}")
            if not detail:
                detail.append("same numbers, different order")
            errors.append(f"phase list does not mirror {loc['files']['plan']}: "
                          f"plan has {len(pnums)}, gatelog has {len(gnums)} "
                          f"({'; '.join(detail)})")
        else:
            plan_by_num = {n: name for n, name, _ in plan}
            for p in phases:
                want = plan_by_num.get(p.number, "")
                if want and p.name and not _names_agree(want, p.name):
                    warn.append(f"Phase {p.number}: plan calls it {want!r}, "
                                f"gatelog calls it {p.name!r}")

    for p in phases:
        if p.status == "done" and not p.findings.strip():
            warn.append(f"Phase {p.number} ({p.name}) is done but its "
                        f"{p.findings_heading or 'Findings'} body is empty")
    return errors, warn


def _names_agree(a, b):
    """Phase names drift a lot in practice; compare only the significant words."""
    def norm(s):
        return [w for w in re.findall(r"[a-z0-9]+", s.lower())
                if w not in ("the", "a", "an", "and", "to", "of", "for", "in")]
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return " ".join(shorter) in " ".join(longer)


# --------------------------------------------------------------------------- #
# next / status
# --------------------------------------------------------------------------- #
def next_phase(phases):
    for p in phases:
        if p.status != "done":
            return p
    return None


def summary(phases, loc, pointer):
    counts = {s: 0 for s in LEGAL_STATUSES}
    for p in phases:
        counts[p.status if p.status in counts else "no status"] = \
            counts.get(p.status if p.status in counts else "no status", 0) + 1
    nxt = next_phase(phases)
    total = len(phases)
    done = sum(1 for p in phases if p.status == "done")
    return {
        "dialect": loc["dialect"],
        "phases": total,
        "done": done,
        "counts": counts,
        "next": nxt.as_dict() if nxt else None,
        "complete": nxt is None,
        "pointer": pointer,
    }


def _load_project(project_dir):
    loc = locate(project_dir)
    if not loc["has_gatelog"]:
        raise GatelogError(f"no gatelog.md in {project_dir} "
                            f"(looked for gatelog.md case-insensitively)")
    path = os.path.join(project_dir, loc["files"]["gatelog"])
    phases, pointer, _ = parse_gatelog(_read(path))
    return loc, phases, pointer


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #
def cmd_locate(args):
    loc = locate(args.project_dir)
    if args.json:
        print(json.dumps(loc, indent=2))
    else:
        print(f"{loc['project_dir']}  dialect={loc['dialect']}")
        for key in STATE_FILES:
            name = loc["files"][key]
            print(f"  {key+'.md':<12} {'found   ' if name else 'MISSING '}"
                  f"{name or ''}")
        for why in loc["legacy_reasons"]:
            print(f"  legacy because: {why}")
    return 0 if loc["has_gatelog"] else 1


def cmd_validate(args):
    loc = locate(args.project_dir)
    errors, warns = validate_project(loc)
    if args.json:
        print(json.dumps({"ok": not errors, "dialect": loc["dialect"],
                          "error_count": len(errors), "errors": errors,
                          "warning_count": len(warns), "warnings": warns},
                         indent=2))
    else:
        for w in warns:
            print(f"WARNING {w}")
        for e in errors:
            print(f"ERROR   {e}")
        if not errors:
            print(f"OK — gatelog is consistent ({len(warns)} warning(s))")
        else:
            print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    return 0 if not errors else 1


def cmd_next(args):
    loc, phases, _ = _load_project(args.project_dir)
    nxt = next_phase(phases)
    if nxt is None:
        out = {"phase": None, "complete": True}
    else:
        out = nxt.as_dict()
        out["complete"] = False
    if args.json:
        print(json.dumps(out, indent=2))
    elif nxt is None:
        print("All phases complete")
    else:
        print(f"Phase {nxt.number}: {nxt.name}  [{nxt.status}]"
              + (f"  test suite: {nxt.test_suite}" if nxt.test_suite else ""))
    _ = loc
    return 0


def cmd_status(args):
    loc, phases, pointer = _load_project(args.project_dir)
    s = summary(phases, loc, pointer)
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        c = s["counts"]
        print(f"{os.path.basename(os.path.normpath(args.project_dir))}: "
              f"{s['phases']} phases ({s['dialect']} dialect) — "
              f"{c.get('done', 0)} done, {c.get('in progress', 0)} in progress, "
              f"{c.get('not started', 0)} not started")
        if s["complete"]:
            print("  All phases complete")
        else:
            n = s["next"]
            print(f"  next: Phase {n['phase']}: {n['name']} [{n['status']}]")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="gatelog_check.py",
        description="dev-sprint gatelog locator/validator")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in (
            ("locate", cmd_locate, "find state files, report the dialect"),
            ("validate", cmd_validate, "check gatelog/plan consistency"),
            ("next", cmd_next, "the first phase that is not done"),
            ("status", cmd_status, "one-line human summary")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("project_dir")
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(func=fn)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        return args.func(args)
    except GatelogError as exc:
        print(f"gatelog_check.py: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:  # never leak a traceback
        print(f"gatelog_check.py: unexpected failure: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
