# Python API

The command line is a thin layer over a few functions you can call directly.

## Files

```python
from lookalike import Options, anonymize, load, save, verify
from lookalike.core import null_test, selector

opts = Options(drop=["ssn"], keep=["quantity"], types={"ref": "uuid"})

ds = load("customers.csv")                     # ds.records is a list of dicts
opts.int_limits = ds.meta.get("int_limits", {})  # only matters for Parquet

records, plans, order = anonymize(ds.records, opts)

dropped = selector(opts.drop)
report = verify(ds.records, records, plans, null_test(opts.null_values), dropped, order)
if not report["passed"]:
    raise SystemExit("\n".join(report["issues"]))

save(ds, records, "safe.csv", dropped)
```

Unlike the command line, this checks the records in memory rather than the
file re-read from disk, and `save` is your call to make. Do not skip
`verify`.

## Records already in memory

`anonymize` takes any list of dicts, lists and scalars; no file is needed.

```python
rows = [
    {"name": "Maria Lopez", "email": "maria@acme.com", "visits": 3},
    {"name": "James Carter", "email": "james@acme.com", "visits": 9},
]
fake_rows, plans, _ = anonymize(rows, Options())
```

## Reference

### `Options`

| Field | Default | Meaning |
|---|---|---|
| `keep` | `[]` | Columns to leave unchanged |
| `drop` | `[]` | Columns to remove |
| `types` | `{}` | `{column: type}` overrides |
| `null_values` | `NULL`, `NA`, ... | Strings treated as blank; `()` for none |
| `locale` | `"en_US"` | Faker locale for names and addresses |
| `preserve_order` | `False` | Keep sort order of numbers and dates |
| `shuffle_rows` | `False` | Randomise row order |
| `seed` | `None` | Fixed seed for reproducible output (tests only) |
| `int_limits` | `{}` | `{column: (min, max)}` bounds for integer columns |

Column names follow the same rules as on the command line; see
[Selecting columns](cli.md#selecting-columns).

### Functions

| Function | Returns |
|---|---|
| `load(path, fmt=None, delimiter=None)` | A `Dataset` with `.fmt`, `.records` and `.meta` |
| `make_plans(records, opts)` | `{column: ColumnPlan}`: the detected type and action per column, without changing anything |
| `anonymize(records, opts)` | `(records, plans, order)`. `order` is `None` unless rows were shuffled; then output row `i` came from input row `order[i]` |
| `verify(original, anonymized, plans, is_null, dropped, order=None, aligned=True)` | The report as a dict; see [Verification](verification.md) |
| `save(dataset, records, path, dropped)` | Writes `records` in the format of `dataset` |

`anonymize` raises `ValueError` for values it cannot handle (for example a
time-of-day in Parquet) and `RuntimeError` when a column has no free values
left to assign.
