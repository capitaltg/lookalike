# Getting started

This walks through one complete run using the sample file in
`examples/customers.csv`. It takes about five minutes.

## 1. Install

```
pip install lookalike
lookalike --help
```

If you work from a clone of this repository instead, run `uv sync` once and
put `uv run` in front of every command below.

## 2. Inspect the file

`inspect` shows how each column will be treated. It prints column names and
counts only, never data.

```
$ lookalike inspect examples/customers.csv
column       type   format    action     non-null  distinct
customer_id  text             anonymize  6         5
full_name    name             anonymize  6         5
email        email            anonymize  6         5
phone        phone            anonymize  6         5
ssn          ssn              anonymize  6         5
city         city             anonymize  6         4
state        state            anonymize  6         3
zip          zip              anonymize  6         5
signup_date  date   %Y-%m-%d  anonymize  6         5
plan         text             anonymize  6         3
balance      float            anonymize  6         4
active       bool             anonymize  5         2
```

Read down the `type` column and check it against what you know about the
data. Two things to look for:

- **A wrong guess.** A column typed `text` still gets anonymized safely (each
  letter becomes another letter, each digit another digit), but the result
  looks like `Kovare Tunib` rather than a name. Fix it with
  `--type COLUMN=TYPE`. See [Column types](column-types.md).
- **Columns you do not need.** The safest column is one that is not there.
  Remove it with `--drop COLUMN`.

## 3. Anonymize

```
$ lookalike anonymize examples/customers.csv safe.csv --report report.json
column       type   action     cells  distinct in  distinct out  check
customer_id  text   anonymize  6      5            5             ok
full_name    name   anonymize  6      5            5             ok
...
active       bool   anonymize  6      2            2             ok

warning: boolean columns have only two possible values; they are randomly swapped or left as is, which hides nothing about the split: active
verification: PASSED (6 records)
```

What happened:

1. Every distinct value in each column was paired with a random fake value.
2. The result was written to a temporary file and read back from disk.
3. That file was compared with the input, column by column.
4. Because every check passed, the file was renamed to `safe.csv`.

`distinct in` and `distinct out` should always be equal: the copy has the
same number of different values per column as the original.

## 4. Read the result

- **`verification: PASSED`** and exit code `0`: `safe.csv` exists and passed
  every check.
- **`verification: FAILED`** and exit code `2`: no output file was written.
  The lines starting with `FAILED:` say which column and why.
- **`warning:` lines** do not block the output. They point at things you
  should decide about yourself:
  - a *boolean* column cannot really be hidden (it only has two values);
  - a column you passed with `--keep` is unchanged;
  - cells such as `NA` or `NULL` were treated as blanks and left alone. If
    those are real values in your data, re-run with `--no-null-tokens`.

## 5. Check again later (optional)

Anyone who has both files can repeat the comparison:

```
lookalike verify examples/customers.csv safe.csv
```

Pass the same `--keep`, `--drop`, `--type` and null options you used when
anonymizing, so the verifier judges each column the same way.

If you use the same options often, save them once as a
[profile](cli.md#profiles) and pass `--profile NAME` instead.

## Next steps

- [Command reference](cli.md) for all options.
- [Privacy guarantees](privacy.md) before sharing output outside your team.
