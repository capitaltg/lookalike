"""Planning and applying the anonymization.

For every column (a CSV header or a JSON path such as ``orders[].email``) a
one-to-one mapping ``original value -> fake value`` is built. Fake values are
drawn from the RNG; the original contributes only its type/shape and its
equality class. The mapping lives in memory only and is never written out.
"""

from __future__ import annotations

import fnmatch
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Context, Decimal
from typing import Any, Callable, Iterator

from . import detect
from .fake import Fakes

DEFAULT_NULLS = ("NULL", "null", "None", "N/A", "n/a", "NA", "NaN", "nan", "#N/A")
SAMPLE = 2000
_CTX = Context(prec=1200)


@dataclass
class Options:
    keep: list[str] = field(default_factory=list)
    drop: list[str] = field(default_factory=list)
    types: dict[str, str] = field(default_factory=dict)
    null_values: tuple[str, ...] = DEFAULT_NULLS
    locale: str = "en_US"
    seed: int | None = None
    preserve_order: bool = False
    shuffle_rows: bool = False
    # Storage bounds of integer columns (path -> (min, max)), e.g. Parquet int8.
    int_limits: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class ColumnPlan:
    path: str
    type: str
    fmt: str | None
    action: str  # "anonymize" | "keep"
    values: int
    distinct: int


def selector(patterns: list[str]) -> Callable[[str], bool]:
    """Predicate matching a path exactly, as a subtree prefix, or by * / ? glob."""
    pats = list(patterns)

    def match(path: str) -> bool:
        for p in pats:
            if path == p or path.startswith(p + ".") or path.startswith(p + "["):
                return True
            if ("*" in p or "?" in p) and fnmatch.fnmatchcase(path, p.replace("[", "[[]")):
                return True
        return False

    return match


def null_test(null_values) -> Callable[[Any], bool]:
    nulls = set(null_values)

    def is_null(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, str):
            return v.strip() == "" or v in nulls
        if isinstance(v, float):
            return not math.isfinite(v)
        if isinstance(v, Decimal):
            return not v.is_finite()
        if isinstance(v, bytes):
            return len(v) == 0
        return False

    return is_null


def walk(node: Any, path: str = "", skip: Callable[[str], bool] | None = None) -> Iterator[tuple[str, Any]]:
    """Yield ``(path, scalar)`` for every leaf of a record tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            if skip and skip(p):
                continue
            yield from walk(v, p, skip)
    elif isinstance(node, (list, tuple)):
        p = path + "[]"
        if skip and skip(p):
            return
        for v in node:
            yield from walk(v, p, skip)
    else:
        yield (path or "$"), node


def rebuild(node: Any, fn: Callable[[str, Any], Any], skip: Callable[[str], bool], path: str = "") -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            if not skip(p):
                out[k] = rebuild(v, fn, skip, p)
        return out
    if isinstance(node, (list, tuple)):
        p = path + "[]"
        return [] if skip(p) else [rebuild(v, fn, skip, p) for v in node]
    return fn(path or "$", node)


def vkey(v: Any) -> tuple[str, Any]:
    """Hashable identity of a value; keeps 1, 1.0, True and "1" apart."""
    return type(v).__name__, v


def _sform(v: Any) -> str | None:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, bytes):
        return None
    return str(v)


def collect(records: list, opts: Options) -> dict[str, Counter]:
    """Per column: Counter of distinct non-null values (keyed by ``vkey``)."""
    is_null = null_test(opts.null_values)
    skip = selector(opts.drop)
    cols: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        for path, v in walk(rec, "", skip):
            if is_null(v):
                cols[path]  # register the column even if it is all null
            else:
                cols[path][vkey(v)] += 1
    return cols


def make_plans(records: list, opts: Options, cols: dict[str, Counter] | None = None) -> dict[str, ColumnPlan]:
    """Decide, deterministically, how each column is treated."""
    cols = collect(records, opts) if cols is None else cols
    keep = selector(opts.keep)
    for p, t in opts.types.items():
        if t not in detect.TYPES:
            raise ValueError(f"unknown type {t!r} for {p!r}; choose from {', '.join(detect.TYPES)}")
    plans = {}
    for path, ctr in cols.items():
        total = sum(ctr.values())
        if keep(path):
            plans[path] = ColumnPlan(path, "kept", None, "keep", total, len(ctr))
            continue
        sample = []
        for _, v in ctr:
            s = _sform(v)
            if s is not None:
                sample.append(s)
            if len(sample) >= SAMPLE:
                break
        typ, fmt = detect.infer(path, sample, complete=len(ctr) <= SAMPLE)
        forced = next((t for p, t in opts.types.items() if selector([p])(path)), None)
        if forced and forced != typ:
            typ, fmt = forced, None
            if forced in ("date", "datetime"):
                found = detect._date_format(sample)
                fmt = found[1] if found and found[0] == forced else ("iso" if forced == "datetime" else "%Y-%m-%d")
        plans[path] = ColumnPlan(path, typ, fmt, "anonymize", total, len(ctr))
    return plans


def _flip(v: Any) -> Any:
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return 1 - v
    partner = detect.BOOL_PAIRS[v.casefold()]
    if v.isupper():
        return partner.upper()
    return partner.capitalize() if v[:1].isupper() else partner


_DT_MAX = datetime.max - datetime.min


class Engine:
    """Builds the per-column value mappings."""

    def __init__(self, opts: Options):
        self.opts = opts
        self.rng = random.Random(opts.seed) if opts.seed is not None else random.SystemRandom()
        self.fakes = Fakes(self.rng, opts.locale)
        self.is_null = null_test(opts.null_values)

    # -- classification --------------------------------------------------
    def _kind(self, plan: ColumnPlan, v: Any) -> tuple[str, Any]:
        T = plan.type
        if isinstance(v, bool):
            return "bool", None
        if T == "bool":
            if isinstance(v, int) and v in (0, 1):
                return "bool", None
            if isinstance(v, str) and detect.is_boolish(v):
                return "bool", None
        if isinstance(v, int):
            return "int", v
        if isinstance(v, float):
            d = Decimal(repr(v))
            return "float", (d, detect.decimals_of(d))
        if isinstance(v, Decimal):
            return "float", (v, detect.decimals_of(v))
        if isinstance(v, datetime):
            return "datetime", v.replace(tzinfo=None)
        if isinstance(v, date):
            return "date", v
        if isinstance(v, bytes):
            return "bytes", None
        if isinstance(v, str):
            if T == "int":
                i = detect.parse_int(v)
                if i is not None:
                    return "int", i
            elif T == "float":
                f = detect.parse_float(v)
                if f is not None:
                    return "float", f
            elif T == "date":
                dt = detect.parse_strptime(v, plan.fmt or "%Y-%m-%d")
                if dt is not None:
                    return "date", dt.date()
            elif T == "datetime":
                dt = detect.parse_iso(v) if plan.fmt == "iso" else detect.parse_strptime(v, plan.fmt)
                if dt is not None:
                    return "datetime", dt
            elif T in self.fakes.GENERATORS:
                return T, None
            return "text", None
        raise ValueError(
            f"column {plan.path!r}: unsupported value type {type(v).__name__}; use --keep or --drop for it"
        )

    # -- mapping construction --------------------------------------------
    def build(self, plan: ColumnPlan, values: list) -> dict:
        """Return ``{vkey(original): fake}`` for the distinct values of a column."""
        try:
            return self._build(plan, values)
        except RuntimeError as e:
            hint = " (try without --preserve-order)" if self.opts.preserve_order else ""
            raise RuntimeError(f"column {plan.path!r}: {e}{hint}") from e

    def _build(self, plan: ColumnPlan, values: list) -> dict:
        self.fakes.new_column()
        groups: dict[str, list] = defaultdict(list)
        for v in values:
            kind, parsed = self._kind(plan, v)
            groups[kind].append((v, parsed))

        out: dict = {}
        used: set = set()
        forbidden = (
            {v.casefold() for v in values if isinstance(v, str)}
            if plan.type not in detect.NON_STRICT
            else set()
        )

        def ukey(x):
            return x.casefold() if isinstance(x, str) else vkey(x)

        def check(orig, fake) -> bool:
            k = ukey(fake)
            if k in used or k == ukey(orig) or self.is_null(fake) or type(fake) is not type(orig):
                return False
            return not (isinstance(fake, str) and (not fake or k in forbidden))

        def accept(orig, fake, checked=False) -> bool:
            if not checked and not check(orig, fake):
                return False
            used.add(ukey(fake))
            out[vkey(orig)] = fake
            return True

        accept.check = check
        accept.ukey = ukey

        if "bool" in groups:
            swap = self.rng.random() < 0.5
            for v, _ in groups.pop("bool"):
                fake = _flip(v) if swap else v
                used.add(ukey(fake))
                out[vkey(v)] = fake

        for kind, items in groups.items():
            if kind == "int":
                self._numeric(
                    items,
                    accept,
                    lambda v, t: t if isinstance(v, int) else str(t),
                    lim=self.opts.int_limits.get(plan.path),
                )
            elif kind == "float":
                self._floats(items, accept)
            elif kind == "date":
                fmt = plan.fmt if plan.type == "date" and plan.fmt else "%Y-%m-%d"
                self._numeric(
                    [(v, d.toordinal()) for v, d in items],
                    accept,
                    lambda v, t: date.fromordinal(t) if isinstance(v, date) else date.fromordinal(t).strftime(fmt),
                    lim=(1, date.max.toordinal()),
                )
            elif kind == "datetime":
                self._datetimes(plan, items, accept)
            elif kind == "bytes":
                for v, _ in items:
                    n = 0
                    while not accept(v, self.rng.randbytes(len(v) + n // 60)):
                        n += 1
            else:
                gen = self.fakes.GENERATORS[kind]
                for v, _ in items:
                    n = 0
                    while True:
                        s = gen(v)
                        if s == v:  # nothing in the value was replaceable
                            s = self.fakes.word(max(1, len(v)))
                        if n >= 60:  # domain looks exhausted: grow the value
                            s = self.fakes.extend(s, 1 + (n - 60) // 20)
                        if accept(v, s):
                            break
                        n += 1
        return out

    def _numeric(self, items, accept, render, lim=None, min_span=0) -> None:
        """Map values on an integer axis to distinct random points of its range.

        ``items`` is ``[(original, tick)]``; ``render(original, tick)`` turns a
        drawn tick into an output value shaped like the original.
        """
        n = len(items)
        lo = min(t for _, t in items)
        hi = max(t for _, t in items)

        def span(lo, hi, need):
            if hi - lo + 1 < need:
                hi = lo + need - 1
            if lim:
                if hi > lim[1]:
                    lo, hi = lo - (hi - lim[1]), lim[1]
                lo = max(lo, lim[0])
            return lo, hi

        lo, hi = span(lo, hi, max(4 * n + 10, min_span))
        exhausted = RuntimeError("could not find free values; the value range of a column is exhausted")
        if self.opts.preserve_order:
            # All-or-nothing: redraw the whole column until every value is valid,
            # so the order is never broken by individual retries.
            ordered = sorted(items, key=lambda it: it[1])
            for attempt in range(1, 201):
                if hi - lo + 1 < n:
                    raise exhausted
                ticks: set[int] = set()
                while len(ticks) < n:
                    ticks.add(self.rng.randint(lo, hi))
                fakes = [render(v, t) for (v, _), t in zip(ordered, sorted(ticks))]
                if len({accept.ukey(f) for f in fakes}) == n and all(
                    accept.check(v, f) for (v, _), f in zip(ordered, fakes)
                ):
                    for (v, _), f in zip(ordered, fakes):
                        accept(v, f, checked=True)
                    return
                if attempt % 10 == 0:
                    lo, hi = span(lo, hi, 2 * (hi - lo + 1))
            raise exhausted
        for v, _ in items:
            tries = 0
            while not accept(v, render(v, self.rng.randint(lo, hi))):
                tries += 1
                if tries % 50 == 0:
                    lo, hi = span(lo, hi, 2 * (hi - lo + 1))
                if tries > 20000:
                    raise exhausted

    def _floats(self, items, accept) -> None:
        dmax = max(d for _, (_, d) in items)

        def tick(x: Decimal) -> int:
            return int(x.scaleb(dmax, _CTX).to_integral_value(ROUND_FLOOR, _CTX))

        def render(v, t):
            d = dmax if self.opts.preserve_order else detect.decimals_of(
                v if isinstance(v, Decimal) else Decimal(repr(v) if isinstance(v, float) else v)
            )
            val = Decimal(t // 10 ** (dmax - d)).scaleb(-d, _CTX)
            if isinstance(v, float):
                return float(val)
            if isinstance(v, Decimal):
                return val
            return f"{val:.{d}f}"

        ticked = [(v, tick(x)) for v, (x, _) in items]
        # Floats carry ~17 significant digits: make sure the range is wide enough,
        # relative to the magnitude, for distinct ticks to be distinct floats.
        mag = max(abs(t) for _, t in ticked)
        lim = None
        if any(isinstance(v, float) for v, _ in items):
            top = tick(Decimal(repr(sys.float_info.max)))
            lim = (-top, top)
        self._numeric(ticked, accept, render, lim=lim, min_span=mag // 10**12)

    def _datetimes(self, plan: ColumnPlan, items, accept) -> None:
        micro = any(dt.microsecond for _, dt in items)
        unit = timedelta(microseconds=1) if micro else timedelta(seconds=1)

        def render(v, t):
            dt = datetime.min + t * unit
            if isinstance(v, datetime):
                return dt.replace(tzinfo=v.tzinfo)
            if plan.fmt != "iso":
                return dt.strftime(plan.fmt)
            m = detect.ISO_DT.fullmatch(v)
            s = f"{dt:%Y-%m-%d}{m.group(2)}{dt:%H:%M}"
            if m.group(5) is not None:
                s += f":{dt:%S}"
            if m.group(6) is not None:
                k = len(m.group(6))
                s += "." + (f"{dt.microsecond:06d}"[:k] if micro else self.fakes.digits(k)).ljust(k, "0")
            return s + (m.group(7) or "")

        self._numeric(
            [(v, (dt - datetime.min) // unit) for v, dt in items],
            accept,
            render,
            lim=(0, _DT_MAX // unit),
        )


def anonymize(records: list, opts: Options) -> tuple[list, dict[str, ColumnPlan], list[int] | None]:
    """Return ``(anonymized records, plans, row order)``.

    ``row order`` is ``None`` unless ``opts.shuffle_rows``; then output row
    ``i`` corresponds to input row ``order[i]``.
    """
    cols = collect(records, opts)
    plans = make_plans(records, opts, cols)
    engine = Engine(opts)
    maps = {
        path: engine.build(plan, [v for _, v in cols[path]])
        for path, plan in plans.items()
        if plan.action == "anonymize"
    }
    is_null = engine.is_null

    def fn(path: str, v: Any) -> Any:
        m = maps.get(path)
        if m is None or is_null(v):
            return v
        return m[vkey(v)]

    skip = selector(opts.drop)
    out = [rebuild(rec, fn, skip) for rec in records]
    order = None
    if opts.shuffle_rows and len(out) > 1:
        order = list(range(len(out)))
        engine.rng.shuffle(order)
        out = [out[i] for i in order]
    return out, plans, order
