"""Command line interface: anonymize, inspect, verify."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__ as _  # noqa: F401
from . import config, detect
from .core import DEFAULT_NULLS, Options, anonymize, make_plans, null_test, selector
from .io import FORMATS, load, save
from .verify import verify


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", choices=FORMATS, help="file format (default: from the extension)")
    p.add_argument("--delimiter", help="CSV delimiter (default: sniffed; tab for .tsv)")
    p.add_argument("--keep", action="append", default=[], metavar="COLUMN",
                   help="pass a column through unchanged (repeatable; * globs and JSON paths allowed)")
    p.add_argument("--drop", action="append", default=[], metavar="COLUMN",
                   help="remove a column from the output (repeatable)")
    p.add_argument("--type", action="append", default=[], metavar="COLUMN=TYPE", dest="types",
                   help=f"override the detected type (repeatable). Types: {', '.join(detect.TYPES)}, "
                   "or regex:PATTERN for values matching your own pattern, e.g. 'code=regex:[0-9]{2}-[A-Z]{5}'")
    p.add_argument("--null-value", action="append", metavar="TOKEN", dest="nulls",
                   help=f"string treated as null and left as is (repeatable; default: {', '.join(DEFAULT_NULLS)})")
    p.add_argument("--no-null-tokens", action="store_true",
                   help="treat only empty cells as null; NA, NULL etc. are anonymized like any value")
    p.add_argument("--config", metavar="FILE",
                   help=f"config file holding profiles (default: ${config.ENV_VAR}, ./{config.LOCAL_NAME}, "
                   "then ~/.config/lookalike/config.toml)")


def _run_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", metavar="NAME",
                   help="start from the options saved under [NAME] in the config file; "
                   "options given on the command line are added on top")


def _anonymize_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--locale", help="Faker locale for names and addresses (default en_US)")
    p.add_argument("--preserve-order", action="store_true",
                   help="keep the sort order of numeric and date columns (leaks rank; off by default)")
    p.add_argument("--shuffle-rows", action="store_true", help="output rows in random order")


def _parse_types(items: list[str]) -> dict[str, str]:
    types = {}
    for item in items:
        cut = item.find("=regex:")
        if cut > 0:  # the pattern itself may contain "=", so split at the first "=regex:"
            col, sep, typ = item[:cut], "=", item[cut + 1 :]
        else:
            col, sep, typ = item.rpartition("=")
        if not sep or not col:
            raise ValueError(f"--type expects COLUMN=TYPE, got {item!r}")
        types[col] = typ
    return types


def _cli_settings(a: argparse.Namespace) -> dict:
    """The options given on the command line, in the shape of a config profile."""
    s: dict = {}
    if a.keep:
        s["keep"] = list(a.keep)
    if a.drop:
        s["drop"] = list(a.drop)
    if a.no_null_tokens:
        s["no_null_tokens"] = True
    elif a.nulls:
        s["null_values"] = list(a.nulls)
    for k in ("preserve_order", "shuffle_rows"):
        if getattr(a, k, False):
            s[k] = True
    for k in ("format", "delimiter", "locale"):
        if getattr(a, k, None):
            s[k] = getattr(a, k)
    types = _parse_types(a.types)
    if types:
        s["types"] = types
    return s


def _resolve(a: argparse.Namespace) -> dict:
    """Profile settings with the command line on top.

    Lists (keep, drop) and types add up, with the command line winning for a
    column named in both; a single-valued option on the command line replaces
    the profile's. Null handling is one choice: either source may make it, and
    the command line wins.
    """
    cli = _cli_settings(a)
    if not a.profile:
        return cli
    s = dict(config.load_profile(a.profile, a.config))
    if "no_null_tokens" in cli or "null_values" in cli:
        s.pop("no_null_tokens", None)
        s.pop("null_values", None)
    for k, v in cli.items():
        if k in ("keep", "drop"):
            s[k] = list(s.get(k, [])) + v
        elif k == "types":
            # Command line entries go first: the first matching selector decides a
            # column's type, so --type email=uuid beats a profile's "*" = "text".
            s[k] = {**v, **{c: t for c, t in s.get(k, {}).items() if c not in v}}
        else:
            s[k] = v
    if s.get("format") is not None and s["format"] not in FORMATS:
        raise ValueError(f"profile [{a.profile}]: format must be one of {', '.join(FORMATS)}")
    return s


def _options(a: argparse.Namespace) -> Options:
    s = a.settings
    return Options(
        keep=s.get("keep", []),
        drop=s.get("drop", []),
        types=s.get("types", {}),
        null_values=() if s.get("no_null_tokens") else tuple(s.get("null_values", DEFAULT_NULLS)),
        locale=s.get("locale", "en_US"),
        seed=getattr(a, "seed", None),
        preserve_order=s.get("preserve_order", False),
        shuffle_rows=s.get("shuffle_rows", False),
    )


def _kept_names(ds, dropped) -> list[str] | None:
    """Internal CSV column names that survive --drop (None for other formats)."""
    if ds.fmt != "csv":
        return None
    return [n for n in ds.meta["names"] if not dropped(n)]


def _header_issues(orig, written, dropped) -> list[str]:
    """CSV header text must survive unchanged (minus dropped columns)."""
    if orig.fmt != "csv":
        return []
    want = [h for h, n in zip(orig.meta["header"], orig.meta["names"]) if not dropped(n)]
    return [] if written.meta["header"] == want else ["CSV header differs from the original"]


def _check_report_path(report: str | None, *others: Path) -> None:
    if not report:
        return
    rp = Path(report)
    for o in others:
        if rp.resolve() == o.resolve() or (rp.exists() and o.exists() and os.path.samefile(rp, o)):
            raise ValueError("--report must not point at the input or output file")


def _table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def _summary(report: dict) -> str:
    rows = [["column", "type", "action", "cells", "distinct in", "distinct out", "check"]]
    for path, c in report["columns"].items():
        rows.append([
            path, c["type"], c["action"], str(c["cells"]),
            str(c["distinct_in"]), str(c["distinct_out"]), "ok" if c["passed"] else "FAIL",
        ])  # fmt: skip
    out = [_table(rows), ""]
    out += [f"warning: {w}" for w in report["warnings"]]
    out += [f"FAILED: {i}" for i in report["issues"][:50]]
    if len(report["issues"]) > 50:
        out.append(f"... and {len(report['issues']) - 50} more issues")
    out.append(f"verification: {'PASSED' if report['passed'] else 'FAILED'} ({report['records']} records)")
    return "\n".join(out)


def cmd_inspect(a: argparse.Namespace) -> int:
    opts = _options(a)
    ds = load(a.input, a.format, a.delimiter)
    plans = make_plans(ds.records, opts)
    rows = [["column", "type", "format", "action", "non-null", "distinct"]]
    for p in plans.values():
        rows.append([p.path, p.type, p.fmt or "", p.action, str(p.values), str(p.distinct)])
    print(_table(rows))
    return 0


def cmd_anonymize(a: argparse.Namespace) -> int:
    opts = _options(a)
    src, dst = Path(a.input), Path(a.output)
    if dst.exists() and src.resolve() == dst.resolve():
        raise ValueError("output must not be the input file")
    _check_report_path(a.report, src, dst)
    ds = load(src, a.format, a.delimiter)
    opts.int_limits = ds.meta.get("int_limits", {})
    records, plans, order = anonymize(ds.records, opts)
    dropped = selector(opts.drop)

    # Write to a temporary file, read it back from disk and verify *that*
    # before it is allowed to take the output name.
    tmp = dst.with_name(dst.name + ".unverified")
    try:
        save(ds, records, tmp, dropped)
        written = load(tmp, ds.fmt, ds.meta.get("delimiter"), _kept_names(ds, dropped))
        report = verify(
            ds.records, written.records, plans, null_test(opts.null_values), dropped, order,
            extra_issues=_header_issues(ds, written, dropped),
        )  # fmt: skip
        if report["passed"]:
            os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()

    report = {
        "tool": "lookalike",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": src.name,
        "output": dst.name,
        "randomness": "seeded PRNG (reproducible; testing only)" if opts.seed is not None else "operating system CSPRNG",
        **({"profile": a.profile} if a.profile else {}),
        "options": {k: v for k, v in asdict(opts).items() if k not in ("seed", "int_limits")},
        "rows_shuffled": order is not None,
        **report,
    }
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    print(_summary(report), file=sys.stderr)
    if not report["passed"]:
        print("no output was written because verification failed", file=sys.stderr)
        return 2
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    opts = _options(a)
    _check_report_path(a.report, Path(a.original), Path(a.anonymized))
    orig = load(a.original, a.format, a.delimiter)
    anon = load(
        a.anonymized, a.format or orig.fmt, a.delimiter or orig.meta.get("delimiter"),
        _kept_names(orig, selector(opts.drop)),
    )  # fmt: skip
    plans = make_plans(orig.records, opts)
    report = verify(
        orig.records, anon.records, plans, null_test(opts.null_values),
        selector(opts.drop), aligned=not (a.unordered or a.settings.get("shuffle_rows", False)),
        extra_issues=_header_issues(orig, anon, selector(opts.drop)),
    )  # fmt: skip
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    print(_summary(report), file=sys.stderr)
    return 0 if report["passed"] else 2


def cmd_profile_save(a: argparse.Namespace) -> int:
    prof = _cli_settings(a)
    make_plans([], Options(types=prof.get("types", {})))  # reject unknown types and unusable patterns now
    path = config.save_profile(a.name, prof, a.config)
    print(f"saved profile [{a.name}] to {path}", file=sys.stderr)
    print(f"use it with: lookalike anonymize INPUT OUTPUT --profile {a.name}", file=sys.stderr)
    return 0


def cmd_profile_list(a: argparse.Namespace) -> int:
    path = config.find(a.config)
    if path is None:
        print(f"no config file (looked for ./{config.LOCAL_NAME} and {config.user_path()})", file=sys.stderr)
        return 0
    print(f"# {path}")
    profiles = config.load_all(path)
    print("\n".join(config.render(n, p) for n, p in profiles.items()), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="lookalike",
        description="Replace every value of a structured data file with random fake data of the same "
        "type and shape, keeping each column's uniqueness cardinality and value frequencies.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("anonymize", help="write an anonymized copy of a file and verify it")
    p.add_argument("input")
    p.add_argument("output")
    _common(p)
    _run_options(p)
    _anonymize_options(p)
    p.add_argument("--report", metavar="FILE", help="write the verification report (JSON, no data values)")
    p.add_argument("--seed", type=int, help="seed the generator for reproducible output (testing only)")
    p.set_defaults(func=cmd_anonymize)

    p = sub.add_parser("inspect", help="show the detected type of each column; prints no data values")
    p.add_argument("input")
    _common(p)
    _run_options(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("verify", help="re-check an anonymized file against its original "
                       "(pass the same --keep/--drop/--type/--null-value flags used to create it)")
    p.add_argument("original")
    p.add_argument("anonymized")
    _common(p)
    _run_options(p)
    p.add_argument("--unordered", action="store_true", help="the output was written with --shuffle-rows")
    p.add_argument("--report", metavar="FILE", help="write the verification report as JSON")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("profile", help="save and list named sets of options (see --profile)")
    psub = p.add_subparsers(dest="profile_cmd", required=True)
    p = psub.add_parser("save", help="save the given options under a name in the config file",
                        description="Save options under NAME so later runs can use --profile NAME. "
                        "Only option values are stored (column names, types, flags), never data.")
    p.add_argument("name", metavar="NAME")
    _common(p)
    _anonymize_options(p)
    p.set_defaults(func=cmd_profile_save)
    p = psub.add_parser("list", help="print the config file in use and its profiles")
    p.add_argument("--config", metavar="FILE", help="config file to read")
    p.set_defaults(func=cmd_profile_list)

    a = ap.parse_args(argv)
    try:
        if a.cmd != "profile":
            a.settings = _resolve(a)
            a.format, a.delimiter = a.settings.get("format"), a.settings.get("delimiter")
        return a.func(a)
    except (ValueError, RuntimeError, OSError) as e:
        print(f"lookalike: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
