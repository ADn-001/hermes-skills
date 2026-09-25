#!/usr/bin/env python3
"""ledger.py — validate, query and surgically rewrite a codebase-audit ledger.

A ledger is one markdown file (``/home/user/codereview/<project>/ledger.md``)
holding one fenced ```yaml block per finding. Read-only subcommands never write
anything, not even an mtime; the mutating ones rewrite atomically and preserve
every other byte of the document.

Exit codes: 0 clean, 1 a real problem (or a mutation succeeded? no - see below),
2 usage error. Mutating subcommands exit 0 on success, 1 on refusal.

Usage:
    python3 tools/ledger.py validate <ledger.md>
    python3 tools/ledger.py list <ledger.md> [--status S] [--approved true|false]
                                            [--min-sev S] [--json]
    python3 tools/ledger.py find <ledger.md> --approved [--status new] [--json]
    python3 tools/ledger.py next-id <ledger.md> [--project P]
    python3 tools/ledger.py stats <ledger.md> [--json]
    python3 tools/ledger.py stale-assigned <ledger.md> [--older-than-hours N]
                                              [--now ISO] [--json]
    python3 tools/ledger.py set-status <ledger.md> --id ID --status S
                            [--ticket T] [--cron C] [--now ISO] [--json]
    python3 tools/ledger.py retitle <ledger.md> --id ID [--title T]
                            [--severity S] [--category C] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blockyaml as by  # noqa: E402

STATUSES = ("new", "assigned", "ticketed", "resolved", "rejected")
SEVERITIES = ("critical", "high", "medium", "low")
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
REQUIRED_FIELDS = (
    "id", "title", "category", "severity", "location", "description", "impact",
    "suggested_fix", "covered_by_test", "approved", "status", "first_seen",
    "last_seen", "linked_ticket", "linked_cron_job", "overlaps_active_phase",
)
ID_RE = re.compile(r"^CR-([A-Za-z0-9._-]+?)-(\d{4})$")
DEFAULT_OLDER_THAN_HOURS = 26


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
class Entry:
    """One fenced ```yaml block."""

    __slots__ = ("fields", "start_line", "end_line", "fence_open", "fence_close",
                 "block", "index")

    def __init__(self, fields, start_line, end_line, fence_open, fence_close,
                 block=None, index=0):
        self.fields = fields
        self.start_line = start_line      # 1-based line of the ```yaml opener
        self.end_line = end_line          # 1-based line of the closing fence
        self.fence_open = fence_open      # 0-based line indexes into the text
        self.fence_close = fence_close
        self.block = block or by.Block()
        self.index = index

    @property
    def id(self):
        return self.fields.get("id")

    @property
    def line(self):
        """Best line number to blame for this entry's problems."""
        return self.start_line

    def get(self, key, default=None):
        v = self.fields.get(key, default)
        return default if v is None else v

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<Entry {self.id} lines {self.start_line}-{self.end_line}>"


class Problem:
    __slots__ = ("entry_id", "line", "message", "field")

    def __init__(self, entry_id, line, message, field=None):
        self.entry_id = entry_id
        self.line = line
        self.message = message
        self.field = field

    def as_dict(self):
        return {"entry": self.entry_id, "line": self.line, "field": self.field,
                "message": self.message}

    def __str__(self):
        who = self.entry_id or "document"
        where = f":{self.line}" if self.line else ""
        fld = f" [{self.field}]" if self.field else ""
        return f"{who}{where}{fld}: {self.message}"


class LedgerError(Exception):
    """Fatal, reportable problem. The CLI turns this into exit 1, no traceback."""


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def parse_ledger(text):
    """Split ledger text into (header_lines, [Entry]).

    ``header_lines`` is every line that is not part of a fenced yaml block,
    in order — that is what the mutating subcommands re-emit verbatim.
    """
    lines = text.split("\n")
    header, entries = [], []
    i, n, idx = 0, len(lines), 0
    while i < n:
        stripped = lines[i].strip()
        if stripped in ("```yaml", "```yml", "```yaml "):
            open_at = i
            j = i + 1
            body = []
            while j < n and lines[j].strip() != "```":
                body.append(lines[j])
                j += 1
            if j >= n:
                raise LedgerError(
                    f"line {open_at + 1}: unterminated ```yaml block "
                    "(no closing fence)")
            block = by.parse_block("\n".join(body), start_line=open_at + 2)
            ent = Entry(block.fields, open_at + 1, j + 1, open_at, j,
                        block, idx)
            entries.append(ent)
            idx += 1
            i = j + 1
            continue
        header.append(lines[i])
        i += 1
    return header, entries


def load(path):
    """Read a ledger file. Raises LedgerError with a human message on failure."""
    if not os.path.exists(path):
        raise LedgerError(f"no such ledger: {path}")
    if os.path.isdir(path):
        raise LedgerError(f"not a file: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise LedgerError(f"cannot read {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise LedgerError(f"{path} is not valid UTF-8: {exc}") from exc
    try:
        return parse_ledger(text)
    except LedgerError:
        raise
    except Exception as exc:  # defensive: never leak a traceback
        raise LedgerError(f"{path}: malformed document: {exc}") from exc


def _as_date(value, field, eid, line, problems):
    """Parse an ISO date/datetime into a naive datetime, or record a problem."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None
    s = str(value).strip().strip('"').strip("'")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            problems.append(Problem(eid, line, f"{field} is not a real date: {s!r}",
                                    field))
            return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        problems.append(Problem(eid, line,
                                f"{field} is not an ISO date/datetime: {s!r}",
                                field))
        return None


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def validate(entries):
    """Return a list of Problem for every rule violation, in document order."""
    problems = []
    seen = {}
    for e in entries:
        eid = e.id if isinstance(e.id, str) else None
        for err in e.block.errors:
            problems.append(Problem(eid, err.line, f"YAML: {err.message}"))
        for f in REQUIRED_FIELDS:
            if f not in e.fields:
                problems.append(Problem(eid, e.line, f"missing required field {f!r}",
                                        f))
        raw_id = e.fields.get("id")
        if not isinstance(raw_id, str):
            problems.append(Problem(eid, e.line,
                                    f"id is not a string: {raw_id!r}", "id"))
        else:
            m = ID_RE.match(raw_id)
            if not m:
                problems.append(Problem(
                    eid, _line_of(e, "id") or e.line,
                    f"id does not match CR-<project>-NNNN: {raw_id!r}", "id"))
            else:
                if raw_id in seen:
                    problems.append(Problem(
                        raw_id, _line_of(e, "id") or e.line,
                        f"duplicate id, first defined at line {seen[raw_id]}", "id"))
                else:
                    seen[raw_id] = _line_of(e, "id") or e.line
        st = e.fields.get("status")
        if not isinstance(st, str) or st not in STATUSES:
            problems.append(Problem(
                eid, _line_of(e, "status") or e.line,
                f"status must be one of {'|'.join(STATUSES)}, got {st!r}", "status"))
        ap = e.fields.get("approved")
        if not isinstance(ap, bool):
            problems.append(Problem(
                eid, _line_of(e, "approved") or e.line,
                f"approved must be true or false, got {ap!r}", "approved"))
        sev = e.fields.get("severity")
        if not isinstance(sev, str) or sev.lower() not in SEV_ORDER:
            problems.append(Problem(
                eid, _line_of(e, "severity") or e.line,
                f"severity must be one of {'|'.join(SEVERITIES)}, got {sev!r}",
                "severity"))
        first = _as_date(e.fields.get("first_seen"), "first_seen", eid,
                         _line_of(e, "first_seen") or e.line, problems)
        last = _as_date(e.fields.get("last_seen"), "last_seen", eid,
                        _line_of(e, "last_seen") or e.line, problems)
        if first and last:
            f2 = first.replace(tzinfo=None) if first.tzinfo else first
            l2 = last.replace(tzinfo=None) if last.tzinfo else last
            if l2 < f2:
                problems.append(Problem(
                    eid, _line_of(e, "last_seen") or e.line,
                    f"last_seen ({l2.date()}) is earlier than first_seen "
                    f"({f2.date()})", "last_seen"))
    return problems


def _line_of(entry, field):
    """1-based absolute line of ``field`` inside the entry's block, or None."""
    span = entry.block.spans.get(field)
    if not span:
        return None
    return entry.fence_open + 1 + span[0] + 1  # fence_open is 0-based


# --------------------------------------------------------------------------- #
# read-only queries
# --------------------------------------------------------------------------- #
def _matches(e, status=None, approved=None, min_sev=None):
    if status is not None and e.fields.get("status") != status:
        return False
    if approved is not None and e.fields.get("approved") is not approved:
        return False
    if min_sev is not None:
        sev = e.fields.get("severity")
        if not isinstance(sev, str) or SEV_ORDER.get(sev.lower(), 99) > SEV_ORDER.get(
                min_sev.lower(), 99):
            return False
    return True


def entry_summary(e):
    return {
        "id": e.id,
        "severity": e.fields.get("severity"),
        "status": e.fields.get("status"),
        "approved": e.fields.get("approved"),
        "title": e.fields.get("title"),
        "line": e.line,
    }


def cmd_validate(entries, args):
    problems = validate(entries)
    if args.json:
        print(json.dumps({"ok": not problems, "entries": len(entries),
                          "problem_count": len(problems),
                          "problems": [p.as_dict() for p in problems]}, indent=2))
    else:
        if not problems:
            print(f"OK — {len(entries)} entries, 0 problems")
        else:
            for p in problems:
                print(f"{p}")
            print(f"\n{len(problems)} problem(s) in {len(entries)} entries")
    return 0 if not problems else 1


def cmd_list(entries, args):
    sel = [e for e in entries if _matches(e, args.status, args.approved,
                                          args.min_sev)]
    if args.json:
        print(json.dumps([entry_summary(e) for e in sel], indent=2))
    else:
        for e in sel:
            print(f"{e.id}  {e.fields.get('severity')}  {e.fields.get('status')}  "
                  f"{str(e.fields.get('approved')).lower()}  {e.fields.get('title')}")
    return 0


def cmd_find(entries, args):
    """The exact set nightly-support consumes. Hot path — no prose parsing."""
    sel = [e for e in entries if _matches(e, args.status, args.approved, None)]
    if args.json:
        print(json.dumps([entry_summary(e) for e in sel], indent=2))
    else:
        for e in sel:
            print(f"{e.id}  {e.fields.get('severity')}  {e.fields.get('status')}  "
                  f"{str(e.fields.get('approved')).lower()}  {e.fields.get('title')}")
    return 0


def _project_of(entries, override=None):
    if override:
        return override
    counts = {}
    for e in entries:
        if isinstance(e.id, str):
            m = ID_RE.match(e.id)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if not counts:
        raise LedgerError("cannot infer a project name: ledger has no CR-* ids; "
                          "pass --project")
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def next_id(entries, project=None):
    """Next unused CR-<project>-NNNN. Max over ALL entries, never reused."""
    project = _project_of(entries, project)
    highest = 0
    for e in entries:
        if isinstance(e.id, str):
            m = ID_RE.match(e.id)
            if m and m.group(1) == project:
                highest = max(highest, int(m.group(2)))
    return f"CR-{project}-{highest + 1:04d}"


def cmd_next_id(entries, args):
    print(next_id(entries, args.project))
    return 0


def stats(entries):
    by_status = {s: 0 for s in STATUSES}
    by_severity = {s: 0 for s in SEVERITIES}
    approved_true = approved_false = 0
    for e in entries:
        st = e.fields.get("status")
        if isinstance(st, str) and st in by_status:
            by_status[st] += 1
        sev = e.fields.get("severity")
        if isinstance(sev, str) and sev.lower() in by_severity:
            by_severity[sev.lower()] += 1
        if e.fields.get("approved") is True:
            approved_true += 1
        elif e.fields.get("approved") is False:
            approved_false += 1
    open_awaiting = sum(
        1 for e in entries
        if e.fields.get("status") == "new" and e.fields.get("approved") is False)
    approved_not_ticketed = sum(
        1 for e in entries
        if e.fields.get("approved") is True
        and e.fields.get("status") in ("new", "assigned"))
    return {
        "total": len(entries),
        "by_status": by_status,
        "by_severity": by_severity,
        "approved": approved_true,
        "not_approved": approved_false,
        "open_awaiting_approval": open_awaiting,
        "approved_not_ticketed": approved_not_ticketed,
    }


def cmd_stats(entries, args):
    data = stats(entries)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"total: {data['total']}")
        print("by status:   " + "  ".join(f"{k}={v}" for k, v in data["by_status"].items()))
        print("by severity: " + "  ".join(f"{k}={v}" for k, v in data["by_severity"].items()))
        print(f"approved: {data['approved']}   not approved: {data['not_approved']}")
        print(f"open_awaiting_approval: {data['open_awaiting_approval']}")
        print(f"approved_not_ticketed: {data['approved_not_ticketed']}")
    return 0


def stale_assigned(entries, older_than_hours=DEFAULT_OLDER_THAN_HOURS, now=None):
    """The deadlock detector: `assigned` forever, and ticketed with no cron.

    Conservative by design — an entry is only flagged when we can *prove* it is
    stranded (no ticket AND a last_seen old enough). Unparseable dates are
    reported as `unknown`, never as stale.
    """
    now = now or datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    cutoff = now - timedelta(hours=older_than_hours)
    stale, cronless, unknown = [], [], []
    for e in entries:
        st = e.fields.get("status")
        if st == "assigned" and not e.fields.get("linked_ticket"):
            probe = []
            last = _as_date(e.fields.get("last_seen"), "last_seen", e.id, e.line,
                            probe)
            if probe:
                unknown.append(e.id)
                continue
            if last is None:
                unknown.append(e.id)
                continue
            l2 = last.replace(tzinfo=None) if last.tzinfo else last
            if l2 < cutoff:
                stale.append({
                    "id": e.id, "reason": "assigned with no linked_ticket",
                    "status": st, "last_seen": str(e.fields.get("last_seen")),
                    "age_hours": round((now - l2).total_seconds() / 3600.0, 1),
                    "title": e.fields.get("title"), "line": e.line,
                })
        elif st == "ticketed" and not e.fields.get("linked_cron_job"):
            cronless.append({
                "id": e.id, "reason": "ticketed with no linked_cron_job",
                "status": st,
                "linked_ticket": e.fields.get("linked_ticket"),
                "last_seen": str(e.fields.get("last_seen")),
                "title": e.fields.get("title"), "line": e.line,
            })
    return stale, cronless, unknown


def cmd_stale_assigned(entries, args):
    now = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LedgerError(f"--now is not an ISO timestamp: {args.now!r} "
                              f"({exc})") from exc
    stale, cronless, unknown = stale_assigned(entries, args.older_than_hours, now)
    if args.json:
        print(json.dumps({"stale_assigned": stale,
                          "ticketed_without_cron": cronless,
                          "unknown_last_seen": unknown}, indent=2))
    else:
        for item in stale:
            print(f"STALE  {item['id']}  last_seen={item['last_seen']}  "
                  f"age={item['age_hours']}h  {item['reason']}")
        for item in cronless:
            print(f"NOCRON {item['id']}  ticket={item['linked_ticket']}  "
                  f"{item['reason']}")
        for eid in unknown:
            print(f"UNKNOWN {eid}  assigned but last_seen is missing/unparseable "
                  "(not flagged as stale)")
        if not (stale or cronless or unknown):
            print(f"OK — no stranded entries (assigned older than "
                  f"{args.older_than_hours}h with no ticket, no ticketed entry "
                  f"without a cron job)")
    return 1 if stale else 0


# --------------------------------------------------------------------------- #
# surgical, atomic rewriting
# --------------------------------------------------------------------------- #
def find_entries(entries, eid):
    """All entries carrying ``eid``. Caller aborts if more than one."""
    return [e for e in entries if e.id == eid]


def rewrite_fields(path, e, updates):
    """Rewrite ``updates`` (key -> value) inside entry ``e`` only, atomically.

    Every other byte of the document — prose, header, other entries, and the
    exact YAML text of untouched fields — is preserved. This is a targeted
    line-span substitution, never a YAML round-trip.
    """
    lines = open(path, "r", encoding="utf-8").read().split("\n")
    edits = []  # (start, end_exclusive, [replacement lines])
    for key, value in updates.items():
        rendered = by.render_scalar(value)
        span = e.block.spans.get(key)
        if span is not None:
            start, end = span
            # end is inclusive in span-space; convert to an exclusive slice end
            edits.append((e.fence_open + 1 + start, e.fence_open + 2 + end,
                          [f"{key}: {rendered}"]))
        else:
            # a brand-new key: insert immediately before the closing fence
            edits.append((e.fence_close, e.fence_close, [f"{key}: {rendered}"]))
    for start, end, repl in sorted(edits, key=lambda t: -t[0]):
        lines[start:end] = repl
    new_text = "\n".join(lines)
    _atomic_write(path, new_text)
    return new_text


def _atomic_write(path, text):
    """temp file in the same dir + os.replace. Never leaves a torn file."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".ledger-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass  # directory fsync is best-effort


def cmd_set_status(entries, path, args):
    matches = find_entries(entries, args.id)
    if not matches:
        raise LedgerError(f"no entry with id {args.id!r} in {path}")
    if len(matches) > 1:
        lines = ", ".join(str(m.line) for m in matches)
        raise LedgerError(f"id {args.id!r} appears in {len(matches)} blocks "
                          f"(lines {lines}); refusing to guess")
    if args.status not in STATUSES:
        raise LedgerError(f"--status must be one of {'|'.join(STATUSES)}")
    e = matches[0]
    updates = {"status": args.status}
    if args.ticket is not None:
        updates["linked_ticket"] = args.ticket
    if args.cron is not None:
        updates["linked_cron_job"] = args.cron
    updates["last_seen"] = _now_date(args.now)
    rewrite_fields(path, e, updates)
    if args.json:
        print(json.dumps({"updated": args.id, "line": e.line, "fields": updates},
                         indent=2))
    else:
        print(f"updated {args.id} (line {e.line}): " +
              ", ".join(f"{k}={v!r}" for k, v in updates.items()))
    return 0


def cmd_retitle(entries, path, args):
    matches = find_entries(entries, args.id)
    if not matches:
        raise LedgerError(f"no entry with id {args.id!r} in {path}")
    if len(matches) > 1:
        lines = ", ".join(str(m.line) for m in matches)
        raise LedgerError(f"id {args.id!r} appears in {len(matches)} blocks "
                          f"(lines {lines}); refusing to guess")
    updates = {}
    if args.title is not None:
        updates["title"] = args.title
    if args.severity is not None:
        if args.severity not in SEVERITIES:
            raise LedgerError(f"--severity must be one of {'|'.join(SEVERITIES)}")
        updates["severity"] = args.severity
    if args.category is not None:
        updates["category"] = args.category
    if not updates:
        raise LedgerError("retitle needs at least one of --title/--severity/"
                          "--category")
    e = matches[0]
    rewrite_fields(path, e, updates)
    if args.json:
        print(json.dumps({"updated": args.id, "line": e.line, "fields": updates},
                         indent=2))
    else:
        print(f"updated {args.id} (line {e.line}): " +
              ", ".join(f"{k}={v!r}" for k, v in updates.items()))
    return 0


def _now_date(now_iso=None):
    if now_iso:
        try:
            dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LedgerError(f"--now is not an ISO timestamp: {now_iso!r} "
                              f"({exc})") from exc
        return dt.date().isoformat()
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _bool_arg(v):
    if v is None:
        return None
    lv = str(v).strip().lower()
    if lv in ("true", "yes", "1"):
        return True
    if lv in ("false", "no", "0"):
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {v!r}")


def build_parser():
    p = argparse.ArgumentParser(
        prog="ledger.py", description="codebase-audit ledger validator/rewriter")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="check every block, every required field")
    v.add_argument("ledger")
    v.add_argument("--json", action="store_true")

    ls = sub.add_parser("list", help="one line per finding")
    ls.add_argument("ledger")
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--approved", type=_bool_arg, metavar="true|false",
                    nargs="?", const=True,
                    help="filter on approval; bare --approved means true")
    ls.add_argument("--min-sev", choices=SEVERITIES)
    ls.add_argument("--json", action="store_true")

    f = sub.add_parser("find", help="the nightly-support hot path")
    f.add_argument("ledger")
    f.add_argument("--approved", type=_bool_arg, metavar="true|false",
                   nargs="?", const=True,
                   help="bare --approved means approved: true")
    f.add_argument("--status", choices=STATUSES)
    f.add_argument("--json", action="store_true")

    n = sub.add_parser("next-id", help="next unused id (never reused)")
    n.add_argument("ledger")
    n.add_argument("--project")

    st = sub.add_parser("stats", help="counts by status/severity/approval")
    st.add_argument("ledger")
    st.add_argument("--json", action="store_true")

    sa = sub.add_parser("stale-assigned", help="detect the assigned-deadlock")
    sa.add_argument("ledger")
    sa.add_argument("--older-than-hours", type=int, default=DEFAULT_OLDER_THAN_HOURS)
    sa.add_argument("--now", metavar="ISO")
    sa.add_argument("--json", action="store_true")

    ss = sub.add_parser("set-status", help="mutate one entry (atomic)")
    ss.add_argument("ledger")
    ss.add_argument("--id", required=True)
    ss.add_argument("--status", required=True, choices=STATUSES)
    ss.add_argument("--ticket")
    ss.add_argument("--cron")
    ss.add_argument("--now", metavar="ISO")
    ss.add_argument("--json", action="store_true")

    rt = sub.add_parser("retitle", help="mutate one entry's title/severity/category")
    rt.add_argument("ledger")
    rt.add_argument("--id", required=True)
    rt.add_argument("--title")
    rt.add_argument("--severity", choices=SEVERITIES)
    rt.add_argument("--category")
    rt.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        header, entries = load(args.ledger)
        if args.cmd == "validate":
            return cmd_validate(entries, args)
        if args.cmd == "list":
            return cmd_list(entries, args)
        if args.cmd == "find":
            return cmd_find(entries, args)
        if args.cmd == "next-id":
            return cmd_next_id(entries, args)
        if args.cmd == "stats":
            return cmd_stats(entries, args)
        if args.cmd == "stale-assigned":
            return cmd_stale_assigned(entries, args)
        if args.cmd == "set-status":
            return cmd_set_status(entries, args.ledger, args)
        if args.cmd == "retitle":
            return cmd_retitle(entries, args.ledger, args)
        raise LedgerError(f"unknown subcommand {args.cmd!r}")
    except LedgerError as exc:
        print(f"ledger.py: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:  # never leak a traceback into a 3am log
        print(f"ledger.py: unexpected failure: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
