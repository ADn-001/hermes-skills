"""A deliberately narrow, stdlib-only YAML *block* reader.

Scope: exactly the shapes the codebase-audit ledgers use, which is:

    key: value
    key: >-        # folded, strip final newline
    key: |-        # literal, strip final newline
    key: "quoted, with \\u2014 escapes"
    key: null / true / false / 42
    key: [a, b]    # inline list of plain or quoted scalars

Anything outside that scope (nested mappings, anchors, multi-document streams,
tab indentation, block collections) is reported as an error with a line number.
Guessing is worse than failing here: these files drive unattended 3am jobs, and
a wrong parse silently mis-reports a security finding.

Public API:

    Block = namedtuple("Block", "fields spans errors")

    parse_block(text, start_line=1) -> Block
        .fields  dict of key -> python value (str/int/float/bool/None/list)
        .spans   dict of key -> (first_line_index, last_line_index) 0-based into
                 the *lines* array, so callers can do surgical rewrites
        .errors  list of YamlError (never raised)

Line numbers in errors are 1-based and absolute (adjusted by ``start_line``),
so a caller can point at the real file line.
"""

from __future__ import annotations

import re

__all__ = ["YamlError", "Block", "parse_block", "parse_scalar", "render_scalar"]

# key at the start of a line, zero indent, terminated by ':' + (space or EOL)
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")
# A block scalar header is a block indicator plus an optional chomping
# indicator: `|`, `|-`, `|+`, `>`, `>-`, `>+`. The real ledgers use `>-` and `|-`.
_BLOCK_HEAD_RE = re.compile(r"^[|>][+-]?$")

_PLAIN_OK = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ ./:@+*#-]*$")
_RESERVED_PLAIN = {
    "null", "Null", "NULL", "~", "true", "True", "TRUE", "false", "False",
    "FALSE", "yes", "no", "Yes", "No", "on", "off", "On", "Off",
}
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?(?:\d+\.\d*|\.\d+)$")
_ESCAPE_RE = re.compile(r"\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|x[0-9A-Fa-f]{2}|.)", re.S)
_SIMPLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "f": "\f",
    "v": "\v", "a": "\a", "e": "\x1b", '"': '"', "\\": "\\", "/": "/",
    "'": "'", " ": " ", "N": "\x85", "_": "\xa0",
}


class YamlError(Exception):
    """One unparseable spot. Carries an absolute, 1-based line number."""

    def __init__(self, message: str, line: int = 0):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"line {self.line}: {self.message}" if self.line else self.message


class Block:
    """Parse result. Always returned, never raised."""

    __slots__ = ("fields", "spans", "errors")

    def __init__(self, fields=None, spans=None, errors=None):
        self.fields = fields or {}
        self.spans = spans or {}
        self.errors = list(errors or [])

    @property
    def ok(self) -> bool:
        return not self.errors

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Block(fields={self.fields!r}, errors={self.errors!r})"


def _unescape_double(raw: str, line: int) -> str:
    """Decode escapes inside a double-quoted scalar. Unknown escape = error."""
    if not raw.endswith('"') or len(raw) < 2:
        raise YamlError(f"unterminated double-quoted scalar: {raw!r}", line)
    body = raw[1:-1]

    def sub(m: "re.Match[str]") -> str:
        tok = m.group(1)
        if tok[0] in "uU":
            return chr(int(tok[1:], 16))
        if tok[0] == "x":
            return chr(int(tok[1:], 16))
        if tok in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[tok]
        raise YamlError(f"unsupported escape sequence '\\{tok}'", line)

    try:
        return _ESCAPE_RE.sub(sub, body)
    except YamlError:
        raise
    except ValueError as exc:
        raise YamlError(f"bad escape: {exc}", line) from exc


def _split_inline_list(raw: str, line: int) -> list:
    """Split `a, "b, c", d` honouring quotes. Raises YamlError on a bad shape."""
    if not raw.endswith("]"):
        raise YamlError(f"unterminated inline list: {raw!r}", line)
    body = raw[1:-1].strip()
    if not body:
        return []
    items, buf, quote, i = [], [], None, 0
    while i < len(body):
        ch = body[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(body):
                buf.append(body[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if quote:
        raise YamlError("unterminated quote inside inline list", line)
    items.append("".join(buf))
    return [parse_scalar(it, line) for it in items]


def parse_scalar(raw: str, line: int = 0):
    """Parse one inline scalar. Raises YamlError on anything unsupported."""
    s = raw.strip()
    if s == "" or s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if s[0] == '"':
        return _unescape_double(s, line)
    if s[0] == "'":
        if len(s) < 2 or not s.endswith("'"):
            raise YamlError(f"unterminated single-quoted scalar: {raw!r}", line)
        return s[1:-1].replace("''", "'")
    if s[0] == "[":
        return _split_inline_list(s, line)
    if s[0] == "{" or s[0] == "&" or s[0] == "*" or s[0] == "|" or s[0] == ">":
        raise YamlError(f"unsupported YAML construct: {raw!r}", line)
    if _INT_RE.match(s):
        return int(s)
    if _FLOAT_RE.match(s):
        return float(s)
    return s


def render_scalar(value) -> str:
    """Render a python scalar back to inline YAML. Used by the rewriters."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    s = str(value)
    needs_quote = (
        s == ""
        or s.lower() in _RESERVED_PLAIN
        or not _PLAIN_OK.match(s)
        or s != s.strip()
    )
    if not needs_quote:
        return s
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) > 0x7E:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _block_scalar(head: str, body: list, key_line: int):
    """Fold or literal-join a block scalar's body lines. Returns (text, used)."""
    style = head[0]
    chomp = head[1:].strip() if len(head) > 1 else ""
    if chomp not in ("-", "+", ""):
        raise YamlError(f"unsupported block scalar header {head!r}", key_line)

    indents = [len(l) - len(l.lstrip(" ")) for l in body if l.strip()]
    if not indents:
        return "", len(body)
    common = min(indents)
    stripped = [l[common:] if l.strip() else "" for l in body]
    while stripped and not stripped[-1]:
        stripped.pop()
    if style == "|":
        text = "\n".join(stripped)
    else:
        # Folded: lines within a paragraph join with a space; a blank line is a
        # paragraph break, i.e. exactly one newline in the result.
        paragraphs, buf = [], []
        for l in stripped:
            if l == "":
                if buf:
                    paragraphs.append(" ".join(buf))
                    buf = []
            else:
                buf.append(l)
        if buf:
            paragraphs.append(" ".join(buf))
        text = "\n".join(paragraphs)
    if chomp != "+":
        text = text.rstrip("\n")
    return text, len(body)


def parse_block(text: str, start_line: int = 1) -> Block:
    """Parse a block of lines. Never raises; problems land in ``.errors``."""
    fields, spans, errors = {}, {}, []
    if text is None:
        return Block()
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = raw.rstrip("\r")
        ln = start_line + i
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line.startswith((" ", "\t")):
            errors.append(YamlError("unexpected indentation (nested mappings are "
                                    "not supported in this subset)", ln))
            i += 1
            continue
        m = _KEY_RE.match(line)
        if not m:
            errors.append(YamlError(f"cannot parse line: {line.strip()[:80]!r}", ln))
            i += 1
            continue
        key, val = m.group(1), m.group(2)
        if key in fields:
            errors.append(YamlError(f"duplicate key {key!r} in block", ln))
        if val is None or val.strip() == "":
            fields[key] = None
            spans[key] = (i, i)
            i += 1
            continue
        head = val.strip()
        if _BLOCK_HEAD_RE.match(head):
            body, j = [], i + 1
            while j < n:
                nxt = lines[j].rstrip("\r")
                if nxt.strip() == "" or nxt.startswith((" ", "\t")):
                    body.append(nxt)
                    j += 1
                else:
                    break
            # trailing blank lines belong to the document, not the scalar
            while body and body[-1].strip() == "":
                body.pop()
                j -= 1
            try:
                fields[key], _ = _block_scalar(head, body, ln)
            except YamlError as exc:
                fields[key] = None
                errors.append(exc)
            spans[key] = (i, j - 1)
            i = j
            continue
        try:
            fields[key] = parse_scalar(head, ln)
        except YamlError as exc:
            fields[key] = None
            errors.append(exc)
        spans[key] = (i, i)
        i += 1
    return Block(fields, spans, errors)
