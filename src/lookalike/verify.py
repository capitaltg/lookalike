"""Independent verification of an anonymized dataset against its original.

Nothing here uses the mapping that produced the output: it only compares the
two datasets, so it can be re-run by anyone holding both files. The returned
report contains column names and counts, never cell values.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

from . import detect
from .core import ColumnPlan, vkey, walk

PRESERVED_BY_DESIGN = [
    "schema: column names / JSON keys, nesting and record count",
    "position of null / empty values",
    "equality pattern within each column (which cells share a value), hence distinct counts and value frequencies",
    "value shape: type, length, letter case, punctuation layout, number of decimals",
    "approximate min/max range of numeric and date columns",
    "row order (unless --shuffle-rows) and co-occurrence of values within a row",
]


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and (a == b or (a != a and b != b))


def _nkey(v: Any) -> tuple[str, str]:
    return type(v).__name__, str(v)


def _is_container(x: Any) -> bool:
    return isinstance(x, (dict, list, tuple))


def shape_diff(o: Any, a: Any, dropped: Callable[[str], bool], path: str = "") -> str | None:
    """Path of the first structural difference (keys, nesting, list lengths), or None."""
    if isinstance(o, dict):
        if not isinstance(a, dict):
            return path or "$"
        keys = [k for k in o if not dropped(f"{path}.{k}" if path else str(k))]
        if list(a) != keys:
            return path or "$"
        for k in keys:
            d = shape_diff(o[k], a[k], dropped, f"{path}.{k}" if path else str(k))
            if d:
                return d
        return None
    if isinstance(o, (list, tuple)):
        p = path + "[]"
        if not isinstance(a, (list, tuple)):
            return path or "$"
        if dropped(p):
            return None if len(a) == 0 else p
        if len(a) != len(o):
            return p
        for x, y in zip(o, a):
            d = shape_diff(x, y, dropped, p)
            if d:
                return d
        return None
    return (path or "$") if _is_container(a) else None


def verify(
    original: list,
    anonymized: list,
    plans: dict[str, ColumnPlan],
    is_null: Callable[[Any], bool],
    dropped: Callable[[str], bool] = lambda p: False,
    order: list[int] | None = None,
    aligned: bool = True,
    extra_issues: list[str] | None = None,
) -> dict:
    """Check ``anonymized`` against ``original``; return a JSON-able report.

    ``order`` maps output rows back to input rows when rows were shuffled.
    With ``aligned=False`` (shuffled rows, order unknown) only per-column
    aggregate checks are possible.
    """
    issues: list[str] = list(extra_issues or [])
    if order is not None:
        original = [original[i] for i in order]
    if len(original) != len(anonymized):
        issues.append(f"record count differs: {len(original)} vs {len(anonymized)}")
        aligned = False

    src: dict[str, list] = defaultdict(list)
    dst: dict[str, list] = defaultdict(list)
    if aligned:
        for i, (o, a) in enumerate(zip(original, anonymized)):
            where = shape_diff(o, a, dropped)
            ol = list(walk(o, "", dropped))
            al = list(walk(a, ""))
            if where or [p for p, _ in ol] != [p for p, _ in al]:
                issues.append(f"record {i}: structure differs at {where or 'a leaf'}")
                aligned = False
                break
            for (p, ov), (_, av) in zip(ol, al):
                src[p].append(ov)
                dst[p].append(av)
    if not aligned:
        src.clear()
        dst.clear()
        for o in original:
            for p, v in walk(o, "", dropped):
                src[p].append(v)
        for a in anonymized:
            for p, v in walk(a, ""):
                dst[p].append(v)

    for p in dst:
        if dropped(p):
            issues.append(f"{p}: dropped column is present in the output")
    for p in set(src) ^ set(dst):
        issues.append(f"{p}: column present on one side only")

    columns = {}
    for p in src:
        if p not in dst:
            continue
        plan = plans.get(p)
        ov, av = src[p], dst[p]
        col_issues: list[str] = []
        o_vals = [v for v in ov if not is_null(v)]
        a_vals = [v for v in av if not is_null(v)]
        o_ctr = Counter(vkey(v) for v in o_vals)
        a_ctr = Counter(vkey(v) for v in a_vals)
        col: dict[str, Any] = {
            "type": plan.type if plan else "unknown",
            "format": plan.fmt if plan else None,
            "action": plan.action if plan else "unknown",
            "cells": len(ov),
            "nulls": len(ov) - len(o_vals),
            "distinct_in": len(o_ctr),
            "distinct_out": len(a_ctr),
            "uniqueness_in": round(len(o_ctr) / len(o_vals), 6) if o_vals else None,
            "uniqueness_out": round(len(a_ctr) / len(a_vals), 6) if a_vals else None,
            "frequency_distribution_match": sorted(o_ctr.values()) == sorted(a_ctr.values()),
        }
        if plan is None:
            col_issues.append("no plan for this column")
        if len(ov) != len(av):
            col_issues.append(f"cell count differs: {len(ov)} vs {len(av)}")
        if len(o_vals) != len(a_vals):
            col_issues.append("number of null values differs")
        if Counter(_nkey(v) for v in ov if is_null(v)) != Counter(_nkey(v) for v in av if is_null(v)):
            col_issues.append("null values differ")
        if Counter(k[0] for k in o_ctr.elements()) != Counter(k[0] for k in a_ctr.elements()):
            col_issues.append("value types differ")
        tokens = sum(1 for v in ov if isinstance(v, str) and v.strip() and is_null(v))
        col["null_token_cells"] = tokens
        keep = plan is not None and plan.action == "keep"
        if keep:
            if aligned:
                if any(not _same(x, y) for x, y in zip(ov, av)):
                    col_issues.append("kept column was modified")
            elif o_ctr != a_ctr:
                col_issues.append("kept column was modified")
        else:
            if not col["frequency_distribution_match"]:
                col_issues.append("value frequency distribution differs")
            if aligned:
                fwd: dict = {}
                back: dict = {}
                bijective = True
                unchanged = 0
                low_entropy = 0
                nulls_moved = 0
                retyped = 0
                is_bool = plan is not None and plan.type == "bool"
                for x, y in zip(ov, av):
                    nx, ny = is_null(x), is_null(y)
                    if nx or ny:
                        if nx != ny or not _same(x, y):
                            nulls_moved += 1
                        continue
                    kx, ky = vkey(x), vkey(y)
                    if type(x) is not type(y):
                        retyped += 1
                    if fwd.setdefault(kx, ky) != ky or back.setdefault(ky, kx) != kx:
                        bijective = False
                    if isinstance(x, bool) or (
                        is_bool
                        and type(x) is type(y)
                        and ((isinstance(x, int) and x in (0, 1)) or (isinstance(x, str) and detect.is_boolish(x)))
                    ):
                        low_entropy += 1
                    elif _same(x, y) or str(x) == str(y):
                        unchanged += 1
                col["one_to_one"] = bijective
                col["unchanged_cells"] = unchanged
                col["low_entropy_cells"] = low_entropy
                if retyped:
                    col_issues.append(f"{retyped} cells changed their value type")
                if nulls_moved:
                    col_issues.append(f"{nulls_moved} null positions differ")
                if not bijective:
                    col_issues.append("mapping original -> output is not one-to-one")
                if unchanged:
                    col_issues.append(f"{unchanged} cells were left unchanged")
            o_strs = {v.casefold() for v in o_vals if isinstance(v, str)}
            reused = len({v.casefold() for v in a_vals if isinstance(v, str)} & o_strs)
            col["output_values_seen_in_original"] = reused
            strict = plan is not None and plan.type not in detect.NON_STRICT
            col["strict"] = strict
            if strict and reused:
                col_issues.append(f"{reused} output values also occur in the original column")
        col["passed"] = not col_issues
        col["issues"] = col_issues
        columns[p] = col
        issues.extend(f"{p}: {m}" for m in col_issues)

    kept = sorted(p for p, c in columns.items() if c["action"] == "keep")
    low = sorted(p for p, c in columns.items() if c.get("low_entropy_cells"))
    toks = sorted(p for p, c in columns.items() if c.get("null_token_cells") and c["action"] != "keep")
    warnings = []
    if kept:
        warnings.append(f"columns passed through unchanged at your request (--keep): {', '.join(kept)}")
    if low:
        warnings.append(
            "boolean columns have only two possible values; they are randomly swapped or left as is, "
            f"which hides nothing about the split: {', '.join(low)}"
        )
    if toks:
        warnings.append(
            "cells holding a null token (such as NA or NULL) were treated as missing and left as is; "
            f"use --no-null-tokens if these are real values: {', '.join(toks)}"
        )
    if not aligned:
        warnings.append(
            "rows were not aligned: only per-column aggregate checks were run; this cannot show that "
            "every cell changed or that the mapping is one-to-one"
        )
    return {
        "passed": not issues,
        "records": len(original),
        "row_aligned": aligned,
        "issues": issues,
        "warnings": warnings,
        "preserved_by_design": PRESERVED_BY_DESIGN,
        "columns": columns,
    }
