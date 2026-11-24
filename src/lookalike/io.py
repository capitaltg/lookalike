"""Reading and writing structured files as a list of record trees.

Every format is normalised to ``records``: a list whose items are dicts, lists
or scalars. CSV rows become ``{column: str}`` dicts; JSON keeps its nesting.
"""

from __future__ import annotations

import csv
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".tab": "csv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
    ".pq": "parquet",
}
FORMATS = ("csv", "json", "jsonl", "parquet")


@dataclass
class Dataset:
    fmt: str
    records: list
    meta: dict = field(default_factory=dict)


def guess_format(path: str | Path, fmt: str | None = None) -> str:
    if fmt:
        if fmt not in FORMATS:
            raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
        return fmt
    ext = Path(path).suffix.lower()
    if ext not in EXTENSIONS:
        raise ValueError(f"cannot infer format from {ext!r}; pass --format ({', '.join(FORMATS)})")
    return EXTENSIONS[ext]


def _sniff_delimiter(path: Path, f) -> str:
    """Pick the delimiter that parses the first records into the most, equally wide, rows."""
    if path.suffix.lower() in (".tsv", ".tab"):
        return "\t"
    best, width = ",", 1
    for d in (",", "\t", ";", "|"):
        f.seek(0)
        rows = [r for r in itertools.islice(csv.reader(f, delimiter=d), 25) if r]
        # The header must be the widest row (short rows are allowed).
        if rows and len(rows[0]) > width and all(len(r) <= len(rows[0]) for r in rows):
            best, width = d, len(rows[0])
    f.seek(0)
    return best


def _unique_names(header: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    taken = set(header)
    names = []
    for i, h in enumerate(header):
        name = h if h != "" else f"column_{i + 1}"
        if name in seen:
            n = seen[name] + 1
            while f"{name}#{n}" in taken:
                n += 1
            seen[name] = n
            name = f"{name}#{n}"
            taken.add(name)
        else:
            seen[name] = 1
        names.append(name)
    return names


def _pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Parquet support needs pyarrow: pip install 'lookalike[parquet]'") from e
    return pyarrow, pq


def load(
    path: str | Path,
    fmt: str | None = None,
    delimiter: str | None = None,
    names: list[str] | None = None,
) -> Dataset:
    """Load a file. ``names`` overrides the internal CSV column names (used when
    re-reading an output whose duplicate/blank headers were partly dropped)."""
    path = Path(path)
    fmt = guess_format(path, fmt)
    if fmt == "csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            delim = delimiter or _sniff_delimiter(path, f)
            rows = list(csv.reader(f, delimiter=delim))
        if not rows:
            return Dataset(fmt, [], {"delimiter": delim, "header": [], "names": []})
        header = rows[0]
        if names is not None and len(names) != len(header):
            raise ValueError(f"{path}: expected {len(names)} columns, found {len(header)}")
        names = list(names) if names is not None else _unique_names(header)
        records = []
        for n, row in enumerate(rows[1:], start=2):
            if len(row) > len(names):
                raise ValueError(f"{path}: row {n} has {len(row)} cells but the header has {len(names)}")
            records.append(dict(zip(names, row)))
        return Dataset(fmt, records, {"delimiter": delim, "header": header, "names": names})
    if fmt == "json":
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return Dataset(fmt, data, {"top": "list"})
        return Dataset(fmt, [data], {"top": "single"})
    if fmt == "jsonl":
        with open(path, encoding="utf-8-sig") as f:
            return Dataset(fmt, [json.loads(line) for line in f if line.strip()])
    pa, pq = _pyarrow()
    table = pq.read_table(path)
    limits = {}
    for fld in table.schema:
        if pa.types.is_integer(fld.type):
            bits = fld.type.bit_width
            signed = pa.types.is_signed_integer(fld.type)
            limits[fld.name] = (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) if signed else (0, 2**bits - 1)
    return Dataset(fmt, table.to_pylist(), {"schema": table.schema, "int_limits": limits})


def save(
    ds: Dataset,
    records: list,
    path: str | Path,
    dropped: Callable[[str], bool] = lambda p: False,
) -> None:
    """Write ``records`` in the format (and layout) of ``ds``."""
    path = Path(path)
    if ds.fmt == "csv":
        cols = [(h, n) for h, n in zip(ds.meta["header"], ds.meta["names"]) if not dropped(n)]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=ds.meta["delimiter"], lineterminator="\n")
            if ds.meta["names"]:
                w.writerow([h for h, _ in cols])
            for rec in records:
                w.writerow([rec[n] for _, n in cols if n in rec])
    elif ds.fmt == "json":
        data: Any = records if ds.meta.get("top") == "list" else records[0]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    elif ds.fmt == "jsonl":
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    else:
        pa, pq = _pyarrow()
        schema = ds.meta["schema"]
        keep = [fld for fld in schema if not dropped(fld.name)]
        if not keep:
            raise ValueError("cannot drop every column of a Parquet file")
        table = pa.Table.from_pylist(records, schema=pa.schema(keep))
        pq.write_table(table, path)
