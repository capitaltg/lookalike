# File formats

The output is always in the same format and layout as the input. The format
is taken from the file extension; use `--format` when the extension is
missing or misleading.

| Format | Extensions |
|---|---|
| CSV / TSV | `.csv`, `.tsv`, `.tab` |
| JSON | `.json` |
| JSON Lines | `.jsonl`, `.ndjson` |
| Parquet | `.parquet`, `.pq` |

The whole file is loaded into memory, so it needs to fit comfortably in RAM.
As a guide, a 200,000-row, five-column CSV takes about 20 seconds.

## CSV and TSV

- The first row is the header. Headers are not changed.
- The delimiter is detected among comma, tab, semicolon and pipe. `.tsv` and
  `.tab` are always tab. Override with `--delimiter`.
- Files are read as UTF-8 (with or without a byte-order mark) and written as
  UTF-8.
- Every cell is text, so types are detected from the values. Formatting such
  as leading zeros (`00123`) and decimals (`5.00`) is kept.
- Rows shorter than the header are kept as they are. A row longer than the
  header is an error.
- Two columns with the same header are told apart as `name` and `name#2` in
  options and reports; a blank header is `column_N`.

## JSON

- The file may be a list of records or a single object.
- Nesting is kept. Each field is a "column" named by its path: `contact.email`,
  `orders[].total`, `tags[]`. Use these names with `--keep`, `--drop` and
  `--type`. See [Selecting columns](cli.md#selecting-columns).
- Keys are not changed. Values keep their JSON type: numbers stay numbers,
  `true`/`false` stay booleans, `null` stays `null`.
- All items of a list share one column, so the same tag in two records gets
  the same fake.

## JSON Lines

One JSON value per line; blank lines are ignored. Otherwise the same as JSON.

## Parquet

Needs `pyarrow`:

```
pip install "lookalike[parquet]"
```

- The schema is kept exactly; dates, timestamps, decimals and binary columns
  are replaced by values of the same kind.
- Top-level integer columns stay inside what their type can hold (`int8`
  stays within -128 to 127).
- These cases stop with an error instead of writing output:
  - `--drop` on a field nested inside a struct (drop the whole column
    instead);
  - dropping every column;
  - a fixed-width decimal or binary column, or a nested integer, that already
    uses nearly every value its type allows;
  - time-of-day columns, which are not supported. `--keep` or `--drop` them.
