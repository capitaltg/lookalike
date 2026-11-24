# Privacy guarantees

Read this before sharing output outside the group that is allowed to see the
original.

## The short version

- Every value is replaced by a random one. No original value is left in the
  output, and there is no key, hash or lookup table that could turn a fake
  back into the original.
- The *patterns* of the data are kept on purpose: how many distinct values a
  column has, how often each occurs, and where the blanks are.
- That makes the output safe against someone reading it for real names,
  numbers and addresses. It does not make it safe against someone who already
  knows a lot about the people in it and goes looking for their pattern.

Treat the output as de-identified working data, not as something fit for
unrestricted public release.

## Why the fakes cannot be reversed

For each column, `lookalike` lists the distinct values and draws one random
fake for each from the operating system's secure random source. The pairing
is held in memory while the file is written and then discarded. It is never
saved, and it is not computed from the original value.

This is different from hashing or encrypting a value. A hash of a phone
number can be undone by hashing every possible phone number and comparing.
Here there is nothing to compare against: the fake for `Maria Lopez` was
picked at random and would be different on the next run.

The only things a fake takes from its original are:

1. its **shape**: type, length, upper/lower case, punctuation, number of
   decimals;
2. its **identity within the column**: the same original always gets the same
   fake, and different originals get different fakes.

## What is checked on every run

Before the output is saved, it is read back and compared with the input:

- no cell kept its original value;
- in identifier-like columns (names, emails, IDs, free text and similar), no
  output value equals *any* original value from that column, ignoring case;
- originals and fakes pair up one-to-one, so distinct counts and frequencies
  match exactly;
- structure, record count and blank cells are unchanged.

If any check fails, no output file is written. Details are in
[Verification](verification.md).

## What stays visible

Anyone holding the output can see:

| Kept | Example of what it reveals |
|---|---|
| Column names and structure | That the file has an `ssn` or `diagnosis` column |
| Number of records | How many customers there are |
| Which cells are blank | Who has no phone number on file |
| Which cells share a value, and how often | That one customer placed 40 of the 200 orders; that one city accounts for half the rows |
| Value shape | That IDs look like `AA-0000` |
| Rough range of numbers and dates | That balances run from about 0 to 1,250 |
| Row order | If the file was sorted by surname, the fakes are in that order too |
| Which values appear together in a row | That the most common city goes with the most common state |

## How someone could still learn something

- **Frequency.** If an attacker knows the most common surname in your
  customer base is Smith, the most common fake surname is Smith.
- **Rare combinations.** A row that is the only one with a particular mix of
  frequent and rare values can be picked out by someone who knows that
  person's details.
- **Row order.** A file sorted by name, date or ID keeps that order.
- **Small categories.** A column with two or three possible values (yes/no,
  a status) tells you the split whatever the labels are.

## What to do about it

| Risk | Action |
|---|---|
| Columns nobody needs | `--drop` them. This is the most effective step. |
| Meaningful row order | `--shuffle-rows` |
| Free-text notes | `--drop`; scrambled text has no use anyway |
| Column names that give things away | Rename them in the output yourself; `lookalike` does not change headers or JSON keys |
| Very rare values | Remove or group those rows before anonymizing |

## Known limits

- **Booleans.** A two-valued column is randomly swapped or left alone. The
  run prints a warning naming these columns.
- **Null markers.** `NA`, `NULL`, `None`, `N/A`, `NaN` and `#N/A` are treated
  as blanks and left as is. The run warns which columns had them. If they are
  real values in your data (`NA` as a country code), use `--no-null-tokens`.
- **`--keep`.** A kept column is copied unchanged. That is your decision and
  is listed as a warning.
- **`--preserve-order`.** Reveals the rank of every number and date.
- **Chance matches.** A random fake may happen to equal a real value from a
  *different* column, or a real person somewhere in the world may share a
  generated name. Neither is connected to your data.
- **Not preserved across columns or files.** The same ID appearing in two
  columns, or in two files, gets two unrelated fakes.
- **This is not k-anonymity or differential privacy.** If you need a formal
  guarantee of that kind, this tool alone does not provide it.
