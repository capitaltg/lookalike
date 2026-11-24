# Verification

Verification answers one question: *does this output file still contain, or
fail to match the structure of, the original?* It works only from the two
files. It never sees the pairing of originals to fakes, so it can be repeated
by anyone who holds both.

## When it runs

- **Automatically, in `anonymize`.** The output is written to
  `OUTPUT.unverified`, read back from disk, and checked. Only a passing file
  is renamed to `OUTPUT`. A failing one is deleted and the exit code is `2`.
- **On demand, with `verify`.**

  ```
  lookalike verify original.csv anonymized.csv
  ```

  Pass the same `--keep`, `--drop`, `--type`, `--null-value` and
  `--no-null-tokens` options used when anonymizing. They change how columns
  are judged; with different options a good file may be reported as failing.

## The checks

For the file as a whole:

- same number of records;
- same structure in every record: keys, nesting and list lengths (minus
  dropped columns);
- for CSV, the same header.

For each anonymized column:

| Check | Fails when |
|---|---|
| Blanks | A blank cell moved, appeared, disappeared or changed |
| One-to-one | Two originals share a fake, or one original got two fakes |
| Frequencies | The counts per distinct value differ |
| Changed | Any cell still holds its original value |
| Types | A value changed kind (a number became text) |
| No reuse | An output value equals any original value of the same column, ignoring case. Applies to all types except `int`, `float`, `date`, `datetime`, `bool`, `state` and `country`, where overlap is unavoidable or harmless. |

For each kept column: every cell is identical to the original.

Booleans are exempt from the *Changed* check, since a two-valued column that
is always flipped would be as readable as one that never is.

## The report

`--report FILE` writes the results as JSON. It contains column names, the
options you passed and counts. It never contains cell values, so it can be
stored alongside the output as a record of the run.

Top level:

| Field | Meaning |
|---|---|
| `passed` | `true` only if every check passed |
| `issues` | One line per failed check; empty when passed |
| `warnings` | Things that did not fail but deserve a look (kept columns, booleans, null markers) |
| `records` | Number of records compared |
| `row_aligned` | `false` when rows could only be compared as totals (`--unordered`) |
| `randomness` | Secure system source, or seeded |
| `options` | The options used |
| `preserved_by_design` | The properties the tool keeps on purpose |
| `columns` | Per-column results, below |

Per column:

| Field | Meaning |
|---|---|
| `type`, `format`, `action` | How the column was treated |
| `cells`, `nulls` | Total cells and how many were blank |
| `distinct_in`, `distinct_out` | Distinct non-blank values before and after |
| `uniqueness_in`, `uniqueness_out` | Distinct values divided by non-blank cells |
| `frequency_distribution_match` | Value counts are the same before and after |
| `one_to_one` | Originals and fakes pair up exactly |
| `unchanged_cells` | Cells still holding their original value (must be 0) |
| `output_values_seen_in_original` | Output values that also occur among the column's originals |
| `strict` | Whether the previous count must be 0 for this type |
| `low_entropy_cells` | Boolean cells, exempt from the changed check |
| `null_token_cells` | Cells such as `NA` that were treated as blank |
| `passed`, `issues` | Result for this column |

Example:

```json
"email": {
  "type": "email",
  "action": "anonymize",
  "cells": 6,
  "nulls": 0,
  "distinct_in": 5,
  "distinct_out": 5,
  "frequency_distribution_match": true,
  "one_to_one": true,
  "unchanged_cells": 0,
  "output_values_seen_in_original": 0,
  "strict": true,
  "passed": true,
  "issues": []
}
```

## Shuffled rows

When `anonymize` runs with `--shuffle-rows` it remembers the new order for
its own check, so that check is as thorough as usual.

A later `verify` does not know the order. Run it with `--unordered`; it then
compares each column's totals (counts, frequencies, blanks, reuse) but cannot
confirm that every individual cell changed. The summary says so.

## What verification does not tell you

A pass means no value survived and the structure matches. It does not mean
the output is safe to publish: the patterns described in
[Privacy guarantees](privacy.md) are still there by design.
