"""Column type inference from column names and value shapes.

Inference only ever looks at a sample of distinct values and returns a type
label; generators must cope with individual values that do not fit the label.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable

from faker.providers.address.en_US import Provider as _US

US_STATES = {s.casefold() for s in _US.states} | {s.casefold() for s in _US.states_abbr}

BOOL_PAIRS = {
    "true": "false", "false": "true",
    "t": "f", "f": "t",
    "yes": "no", "no": "yes",
    "y": "n", "n": "y",
    "0": "1", "1": "0",
}  # fmt: skip
BOOL_SETS = [{k, v} for k, v in BOOL_PAIRS.items()]

# Types that are filled by a string generator (see fake.Fakes.GENERATORS).
STRING_TYPES = (
    "text", "first_name", "last_name", "name", "email", "phone", "ssn",
    "credit_card", "zip", "ipv4", "uuid", "hex", "mac", "url", "street",
    "address", "address2", "city", "company", "username", "state", "country",
)  # fmt: skip
TYPES = STRING_TYPES + ("bool", "int", "float", "date", "datetime")

# Output values of these types may legitimately coincide with *some* original
# value of the column (small or numeric domains). All other types are "strict":
# no output value may equal any original value of the same column.
NON_STRICT = {"bool", "int", "float", "date", "datetime", "state", "country"}

_INT = re.compile(r"[+-]?(0|[1-9]\d*)")
_FLOAT = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
ISO_DT = re.compile(
    r"(\d{4}-\d{2}-\d{2})([T ])(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?"
)

VALUE_SHAPES = [
    ("email", re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")),
    ("uuid", re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")),
    ("ipv4", re.compile(r"(\d{1,3}\.){3}\d{1,3}")),
    ("mac", re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")),
    ("ssn", re.compile(r"\d{3}-\d{2}-\d{4}")),
    ("url", re.compile(r"https?://\S+")),
]
_PHONE = re.compile(
    r"(\+?1[ .-]?)?(\(\d{3}\) ?|\d{3}[ .-])\d{3}[ .-]\d{4}( ?(x|ext\.?) ?\d+)?", re.I
)
_HEX = re.compile(r"[0-9a-fA-F]{8,}")

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y",
    "%m/%d/%y", "%d.%m.%Y", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y",
]  # fmt: skip
DATETIME_FORMATS = [
    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p",
]  # fmt: skip

_H = {
    "phone": r"phone|mobile|telephone|(^|_)(cell|fax|tel)(_|$)",
    "ssn": r"ssn|social_sec",
    "credit_card": r"credit_?card|card_?(num|no)|(^|_)(cc|pan)(_|$)",
    "zip": r"zip|postal|postcode",
    "company": r"company|employer|organi[sz]ation|business|vendor|supplier|(^|_)org(_|$)",
    "username": r"user_?name|login|screen_?name|(^|_)handle(_|$)",
    "first_name": r"first_?name|fname|given_?name|forename|middle_?name",
    "last_name": r"last_?name|lname|surname|family_?name|maiden",
    "name": r"^(full_?)?name$|(customer|patient|employee|person|contact|member|client|owner"
    r"|student|driver|recipient|sender|manager|author|beneficiary|guardian|physician|doctor"
    r"|provider|agent|rep|full|display|legal|holder)_?name$",
    "address2": r"address_?(line_?)?2|addr_?2|(^|_)(apt|suite|unit)(_|$)",
    "address": r"address|street|addr(_|$|\d)",
    "city": r"city|town|municipality",
    "state": r"(^|_)(state|province|st)(_|$)",
    "country": r"country|nation",
}
HINTS = {k: re.compile(v) for k, v in _H.items()}
_NOT_ADDRESS = re.compile(r"email|e_mail|(^|_)(ip|mac|url|web)(_|$)")


def is_boolish(v: str) -> bool:
    """A boolean token in one of its three plain spellings (true / TRUE / True)."""
    k = v.casefold()
    return k in BOOL_PAIRS and v in (k, k.upper(), k.capitalize())


def hint_name(path: str) -> str:
    """Normalise the last segment of a column path to snake_case."""
    segs = [s for s in re.split(r"[.\[\]]+", path) if s]
    name = segs[-1] if segs else path
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_")


def parse_int(s: str) -> int | None:
    return int(s) if _INT.fullmatch(s) else None


def parse_float(s: str) -> tuple[Decimal, int] | None:
    """Return (value, number of decimals) for a plain or scientific number."""
    if not _FLOAT.fullmatch(s):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or abs(d.adjusted()) > 300:
        return None
    return d, decimals_of(d)


def decimals_of(d: Decimal) -> int:
    return min(340, max(0, -d.as_tuple().exponent))


def parse_iso(s: str) -> datetime | None:
    m = ISO_DT.fullmatch(s)
    if not m:
        return None
    try:
        day = datetime.strptime(m.group(1), "%Y-%m-%d")
        micro = int((m.group(6) or "0")[:6].ljust(6, "0"))
        return day.replace(
            hour=int(m.group(3)),
            minute=int(m.group(4)),
            second=int(m.group(5) or 0),
            microsecond=micro,
        )
    except ValueError:
        return None


def parse_strptime(s: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(s, fmt)
    except ValueError:
        return None


def most(values: list[str], pred: Callable[[str], object], threshold: float = 0.95) -> bool:
    """True if at least ``threshold`` of values satisfy ``pred`` (early exit)."""
    allowed = len(values) - int(len(values) * threshold + 0.999999)
    misses = 0
    for v in values:
        if not pred(v):
            misses += 1
            if misses > allowed:
                return False
    return True


def _digits(s: str) -> int:
    return sum(c.isdigit() for c in s)


def _date_format(sample: list[str]) -> tuple[str, str] | None:
    if not most(sample, lambda x: 6 <= len(x) <= 30 and x[0].isalnum() and _digits(x) >= 3):
        return None
    for kind, fmts in (("date", DATE_FORMATS), ("datetime", DATETIME_FORMATS)):
        for fmt in fmts:
            if most(sample, lambda x: parse_strptime(x, fmt) is not None):
                return kind, fmt
    return None


def infer(path: str, sample: Iterable[str], complete: bool = True) -> tuple[str, str | None]:
    """Infer ``(type, format)`` for a column.

    ``sample`` holds string forms of distinct non-null values; ``complete`` says
    whether it covers every distinct value of the column.
    """
    s = list(sample)
    if not s:
        return "text", None
    h = hint_name(path)
    folded = {x.casefold() for x in s}
    if complete and any(folded <= p for p in BOOL_SETS) and all(is_boolish(x) for x in s):
        return "bool", None
    for t, rx in VALUE_SHAPES:
        if most(s, rx.fullmatch):
            return t, None
    if HINTS["phone"].search(h) and most(s, lambda x: 7 <= _digits(x) <= 15):
        return "phone", None
    if HINTS["ssn"].search(h) and most(s, lambda x: _digits(x) == 9):
        return "ssn", None
    if HINTS["credit_card"].search(h) and most(s, lambda x: 12 <= _digits(x) <= 19):
        return "credit_card", None
    if HINTS["zip"].search(h):
        return "zip", None
    if most(s, lambda x: parse_int(x) is not None):
        return "int", None
    if most(s, lambda x: parse_float(x) is not None):
        return "float", None
    if most(s, lambda x: parse_iso(x) is not None):
        return "datetime", "iso"
    found = _date_format(s)
    if found:
        return found
    if most(s, _PHONE.fullmatch):
        return "phone", None
    for t in ("company", "username", "first_name", "last_name", "name", "address2"):
        if HINTS[t].search(h):
            return t, None
    if HINTS["address"].search(h) and not _NOT_ADDRESS.search(h):
        full = sum("," in x for x in s) * 2 >= len(s)
        return ("address" if full else "street"), None
    if HINTS["city"].search(h):
        return "city", None
    if HINTS["state"].search(h) and most(s, lambda x: x.strip().casefold() in US_STATES):
        return "state", None
    if HINTS["country"].search(h):
        return "country", None
    if most(s, _HEX.fullmatch) and any(c.isalpha() for x in s for c in x):
        return "hex", None
    return "text", None
