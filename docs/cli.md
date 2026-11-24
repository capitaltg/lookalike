# Command reference

```
lookalike inspect   INPUT            [options]
lookalike anonymize INPUT OUTPUT     [options]
lookalike verify    ORIGINAL ANONYMIZED [options]
lookalike profile save NAME          [options]
lookalike profile list
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

### `profile save` and `profile list`

Save a set of options under a name, and show what is saved. See
[Profiles](#profiles).

## Options for all commands

| Option | Meaning |
|---|---|
| `--keep COLUMN` | Leave this column unchanged. Repeatable. Reported as a warning. |
| `--drop COLUMN` | Remove this column from the output. Repeatable. |
| `--type COLUMN=TYPE` | Use this type for this column instead of the detected one, e.g. `--type col7=name`. `TYPE` can also be `regex:PATTERN` to generate values from your own pattern. Repeatable. Types are listed in [Column types](column-types.md). |
| `--null-value TOKEN` | Treat this exact string as a blank and leave it as is. Repeatable; replaces the default list. |
| `--no-null-tokens` | Treat only empty cells as blanks. `NA`, `NULL` and similar are anonymized like any other value. |
| `--format FORMAT` | `csv`, `json`, `jsonl` or `parquet`, when the file extension is not enough. |
| `--delimiter CHAR` | CSV delimiter, when auto-detection picks the wrong one. |
| `--profile NAME` | Start from the options saved under `[NAME]` in the config file. See [Profiles](#profiles). |
| `--config FILE` | Read profiles from this file instead of the default one. |

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

## Profiles

A profile is a named set of options kept in a config file, so you do not have
to retype the same `--type`, `--drop` and `--keep` flags for files you
anonymize regularly. It stores option values only (column names, types,
flags), never data.

Save one from the flags you would otherwise pass:

```
lookalike profile save customers --drop ssn --keep quantity \
    --type col7=name --type 'employee_no=regex:EMP\d{6}'
```

Then use it:

```
lookalike inspect   in.csv         --profile customers
lookalike anonymize in.csv out.csv --profile customers
lookalike verify    in.csv out.csv --profile customers
```

`lookalike profile list` prints the config file in use and its profiles:

```
[customers]
keep = ["quantity"]
drop = ["ssn"]

[customers.types]
col7 = "name"
employee_no = 'regex:EMP\d{6}'
```

The file is [TOML](https://toml.io) and you can write or edit it by hand.
Each `[NAME]` section is one profile. `profile save` only adds new profiles;
to change or remove one, edit the file.

| Setting | Same as | Value |
|---|---|---|
| `keep` | `--keep` | list of columns |
| `drop` | `--drop` | list of columns |
| `[NAME.types]` | `--type` | one `COLUMN = "TYPE"` line per column |
| `null_values` | `--null-value` | list of strings |
| `no_null_tokens` | `--no-null-tokens` | `true` or `false` |
| `format` | `--format` | string |
| `delimiter` | `--delimiter` | string |
| `locale` | `--locale` | string |
| `preserve_order` | `--preserve-order` | `true` or `false` |
| `shuffle_rows` | `--shuffle-rows` | `true` or `false` |

Notes on writing the file by hand:

- Put a column name in quotes if it has anything other than letters, digits,
  `-` and `_` in it: `"orders[].ref" = "uuid"`.
- Write regex patterns in single quotes, so backslashes are taken as they
  are: `'regex:EMP\d{6}'`.
- `--seed` and `--report` cannot be saved.

**Where the file lives.** The first of these is used; files are not combined:

1. the file given with `--config FILE`
2. the file named by the `LOOKALIKE_CONFIG` environment variable
3. `lookalike.toml` in the current directory
4. `~/.config/lookalike/config.toml` (or under `$XDG_CONFIG_HOME`)

`profile save` writes to the same file, creating number 4 if none exists. A
`lookalike.toml` next to your data can be committed with a project so everyone
uses the same options.

**Adding flags to a profile.** Flags on the command line go on top of the
profile:

- `--keep`, `--drop` and `--type` are added to the profile's. If a `--type`
  on the command line and one in the profile cover the same column, the
  command line wins, even when the profile's uses a wildcard.
- `--format`, `--delimiter` and `--locale` replace the profile's value.
- `--null-value` or `--no-null-tokens` replaces whatever the profile says
  about nulls.
- A switch the profile turns on (`shuffle_rows`, `preserve_order`) cannot be
  turned off from the command line; edit the profile or leave `--profile` out.

A profile with `shuffle_rows = true` makes `verify --profile` compare as
`--unordered`. Settings that do not apply to a command are ignored (for
example `locale` in `inspect`).

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

A column called `col7` holds people's names, but its header gives no clue, so
`inspect` shows it as `text`. Tell `lookalike` what it is (`COLUMN=TYPE`):

```
lookalike anonymize in.csv out.csv --type col7=name
```

Employee numbers should look like `EMP` plus six digits, whatever they looked
like before (see [Your own pattern](column-types.md#your-own-pattern-regex)):

```
lookalike anonymize in.csv out.csv --type 'employee_no=regex:EMP\d{6}'
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
