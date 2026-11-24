# Command reference

```
lookalike inspect   INPUT            [options]
lookalike anonymize INPUT OUTPUT     [options]
lookalike verify    ORIGINAL ANONYMIZED [options]
```

## Commands

### `inspect`

Prints one line per column: detected type, date format if any, whether it
will be anonymized or kept, and how many non-null and distinct values it has.
No data values are printed. Use it to decide which options you need.

### `anonymize`

Writes an anonymized copy of `INPUT` to `OUTPUT`, in the same format. The
output is verified before it is given its final name; if verification fails,
no output file is written. `OUTPUT` must not be the input file.

### `verify`

Compares an anonymized file with its original and prints the same summary
`anonymize` does. Pass the same column and null options that were used to
create the file. See [Verification](verification.md).

## Options for all commands

| Option | Meaning |
|---|---|
| `--keep COLUMN` | Leave this column unchanged. Repeatable. Reported as a warning. |
| `--drop COLUMN` | Remove this column from the output. Repeatable. |
| `--type COLUMN=TYPE` | Use this type instead of the detected one. Repeatable. Types are listed in [Column types](column-types.md). |
| `--null-value TOKEN` | Treat this exact string as a blank and leave it as is. Repeatable; replaces the default list. |
| `--no-null-tokens` | Treat only empty cells as blanks. `NA`, `NULL` and similar are anonymized like any other value. |
| `--format FORMAT` | `csv`, `json`, `jsonl` or `parquet`, when the file extension is not enough. |
| `--delimiter CHAR` | CSV delimiter, when auto-detection picks the wrong one. |

By default these strings count as blanks: `NULL`, `null`, `None`, `N/A`,
`n/a`, `NA`, `NaN`, `nan`, `#N/A`. Empty and whitespace-only cells always do.

## Options for `anonymize`

| Option | Meaning |
|---|---|
| `--report FILE` | Save the verification results as JSON. Contains column names, your options and counts; no cell values. |
| `--shuffle-rows` | Write the rows in random order. Use this when the original order itself gives something away (for example, sorted by surname). |
| `--preserve-order` | Numeric and date columns keep their sort order: the smallest original becomes the smallest fake, and so on. Reveals rank; off by default. |
| `--locale LOCALE` | Language/region for fake names and addresses, e.g. `en_GB`, `de_DE`. Default `en_US`. |
| `--seed N` | Produce the same output every run. For tests only; without it the operating system's secure random source is used. |

## Options for `verify`

| Option | Meaning |
|---|---|
| `--unordered` | The output was written with `--shuffle-rows`. Only per-column totals can be compared in this mode. |
| `--report FILE` | Save the results as JSON. |

## Selecting columns

`COLUMN` in `--keep`, `--drop` and `--type` is:

- for CSV and Parquet, the column header: `--drop ssn`
- for JSON, the path to the field, with `.` between levels and `[]` after a
  list: `--drop contact.email`, `--keep tags[]`, `--type orders[].ref=uuid`

Two shortcuts:

- A path also selects everything under it: `--drop contact` removes
  `contact.email`, `contact.phones[]` and so on.
- `*` and `?` work as wildcards: `--drop "*_internal"`.

Run `inspect` to see the exact names. If a CSV has two columns with the same
header, the second is called `name#2`; a blank header is called `column_N`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. For `anonymize`, the output was written and verified. |
| `1` | Could not run: unreadable file, unknown format, bad option value. |
| `2` | Verification failed (no output written), or the command line was invalid. |

## Recipes

Drop what you do not need, keep a non-sensitive measure:

```
lookalike anonymize orders.csv out.csv --drop notes --drop ssn --keep quantity
```

A reference column was typed `text` but holds UUIDs with odd formatting:

```
lookalike anonymize in.csv out.csv --type ref=uuid
```

`NA` is a real country code in this file, not a blank:

```
lookalike anonymize in.csv out.csv --no-null-tokens
```

Hide the row order and check the result later:

```
lookalike anonymize in.jsonl out.jsonl --shuffle-rows
lookalike verify    in.jsonl out.jsonl --unordered
```

Semicolon-separated file with a `.txt` extension:

```
lookalike anonymize export.txt out.txt --format csv --delimiter ";"
```
