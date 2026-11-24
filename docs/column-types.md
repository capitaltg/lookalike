# Column types

Every column gets one type. The type decides what the fake values look like;
it does not decide *whether* the column is anonymized. Every column is, unless
you `--keep` it.

Run `lookalike inspect FILE` to see the detected types, and override any of
them with `--type COLUMN=TYPE`. For a format none of the types covers, give
[your own pattern](#your-own-pattern-regex).

## How detection works

`lookalike` looks at the column name and at up to 2,000 distinct values. A
type is chosen when at least 95% of those values fit it. Rules are tried in
this order; the first match wins.

| Step | Types | Decided by |
|---|---|---|
| 1 | `bool` | Every value is one of a pair: `true/false`, `t/f`, `yes/no`, `y/n`, `0/1` |
| 2 | `email`, `uuid`, `ipv4`, `mac`, `ssn`, `url` | The values' shape alone |
| 3 | `phone`, `ssn`, `credit_card`, `zip` | A telling column name (`phone`, `mobile`, `ssn`, `card_number`, `zip`, `postal_code`, ...) plus a plausible digit count |
| 4 | `int`, `float` | Values are numbers |
| 5 | `datetime`, `date` | Values parse as dates (formats below) |
| 6 | `phone` | Values are formatted like US phone numbers |
| 7 | `company`, `username`, `first_name`, `last_name`, `name`, `address2`, `address`, `street`, `city`, `state`, `country` | The column name (`first_name`, `surname`, `customer_name`, `street`, `city`, ...) |
| 8 | `hex` | Values are 8 or more hexadecimal characters |
| 9 | `text` | Everything else |

Names such as `firstName`, `First Name` and `first_name` are treated alike.
For JSON, the last part of the path is used (`contact.email` is judged as
`email`).

Names of people, companies and places cannot be recognised from their values,
so those types depend on the column name. If your column is called `col7`,
tell `lookalike` what it is: `--type col7=name`.

Recognised date formats: `2024-03-15`, `03/15/2024`, `15/03/2024`,
`2024/03/15`, `03-15-2024`, `15-03-2024`, `03/15/24`, `15.03.2024`,
`15-Mar-2024`, `Mar 15, 2024`, `March 15, 2024`. Date-times: ISO 8601
(`2024-03-15T09:30:00Z`, `2024-03-15 09:30`) and `03/15/2024 09:30` with
optional seconds or AM/PM.

## What each type produces

Fakes copy the *shape* of the original (length, upper/lower case, punctuation)
and nothing else.

| Type | Original | Fake | Notes |
|---|---|---|---|
| `text` | `CU-1001`, `gold` | `ZO-7893`, `vasa` | Letter for letter, digit for digit. Used for IDs, codes, categories, free text. |
| `first_name`, `last_name` | `Maria` | `April` | |
| `name` | `Maria Lopez`, `LOPEZ, MARIA` | `Scott Kirby`, `KIRBY, SCOTT` | Keeps "Last, First" order and capitalisation. |
| `email` | `maria@acme.com` | `ojones692@bajecoro.example` | `.example` can never be a real domain. Addresses that shared a domain still share one. |
| `phone` | `(703) 281-4410` | `(249) 555-4032` | US numbers use the 555 exchange. Other lengths get random digits in the same layout. |
| `ssn` | `514-22-9081` | `000-62-2439` | Area `000` or `666`, which are never issued. |
| `credit_card` | `4111 1111 1111 1111` | `7302 5518 0946 2213` | Same layout, passes the Luhn checksum. |
| `zip` | `20190`, `20190-1234` | `27589`, `54009-8812` | |
| `street` | `12 Oak St` | `787 Swanson Road` | |
| `address` | `12 Oak St, Reston, VA 20190` | `326 Wesley Path, Lake Amy, OH 44512` | Chosen when most values contain a comma. |
| `address2` | `Apt 4` | `Suite 212` | |
| `city` | `Reston` | `West Jasonborough` | |
| `state` | `VA`, `Virginia` | `CO`, `Colorado` | Another US state, same style. Only chosen when the values really are US states. |
| `country` | `US`, `France` | `PT`, `Malaysia` | Code or name, matching the original. |
| `company` | `Acme Inc` | `Bowman, Hall and Reyes` | |
| `username` | `mlopez` | `hartdaniel` | |
| `uuid` | `3f2b8c1e-...` | a new random UUID | |
| `ipv4` | `52.14.8.9` | `10.44.201.7` | Always in the private `10.x.x.x` range. |
| `mac`, `hex` | `a4:5e:60:c1:02:9f` | `0b:7d:e1:44:9a:c3` | |
| `url` | `https://acme.com/a/b` | `https://kovarin.example/tulo` | |
| `int` | `42` | `17` | A random whole number between the column's smallest and largest value. |
| `float` | `1250.40` | `954.47` | Same, with the same number of decimals. |
| `date`, `datetime` | `2023-04-12` | `2023-10-17` | A random moment between the column's earliest and latest, in the same format. |
| `bool` | `true` | `true` or `false` | The whole column is either swapped or left alone, by coin flip. See [Privacy guarantees](privacy.md). |

## Your own pattern: `regex:`

When none of the built-in types gives the format you want, describe it with a
regular expression. Put `regex:` in front of the pattern:

```
lookalike anonymize in.csv out.csv --type 'code=regex:[0-9]{2}-[A-Z]{5}'
```

Every value in the `code` column is replaced by a random string that matches
the pattern, such as `66-QNIDO` or `02-VTIDA`. As with every other type, equal
originals get the same fake and different originals get different fakes.

Put the whole option in single quotes so the shell does not interpret the
brackets and braces.

Unlike the built-in types, the fake takes nothing from the original, not even
its length: the pattern alone decides the shape. The originals do not have to
match the pattern.

| Pattern | Produces |
|---|---|
| `[0-9]{2}-[A-Z]{5}` | `66-QNIDO` |
| `(INV\|PO)-\d{4,6}` | `PO-48213`, `INV-0931` |
| `[A-Z]{3}\d{3}[a-f]` | `QTM402c` |
| `EMP\d{6}` | `EMP550917` |
| `[A-Z][a-z]{3,8}` | `Tgkwa`, `Mzoqplrn` |

What you can use:

- literal characters, `.`, classes such as `[A-Z0-9_]` and `[^,]`, and `\d`,
  `\w`, `\s` (with `\D`, `\W`, `\S`);
- repeats: `{3}`, `{2,5}`, `?`, `*`, `+`;
- groups and alternatives: `(AB|CD)`, `(?:...)`.

Details:

- `*`, `+` and `{2,}` have no upper limit in a regular expression; `lookalike`
  produces at most 8 more than the minimum.
- `.` gives a letter or digit. Negated classes (`[^,]`, `\D`, `\W`, `\S`)
  draw from plain ASCII letters, digits and punctuation.
- A pattern may not produce values longer than 1,000 characters.
- Back-references (`\1`) and look-ahead/look-behind are not supported and are
  rejected with an error.
- The pattern must allow enough different values. A column with 500 distinct
  values cannot be filled from `[A-Z]` (26 possibilities); the run stops with
  an error naming the column, and nothing is written. Text values already
  present in the column are never reused, so allow some room.
- Verification also checks that every output value matches the pattern. When
  you run `verify` later, pass the same `--type` option.
- JSON numbers and booleans in the column stay numbers and booleans; the
  pattern applies to text values.

## Good to know

- **A value that does not fit its column's type** (a stray `unknown` in a date
  column) is anonymized as `text`. Nothing is skipped.
- **Small sets fill up.** If a column uses most of what its shape allows
  (every two-digit code, every US state), fakes may come out longer, or as
  something that is not a real state, rather than repeat.
- **Numbers and dates are redrawn evenly across the range.** The number of
  distinct values is kept; the average and the shape of the distribution are
  not. Use `--preserve-order` if sort order matters, or `--keep` if the
  numbers are not sensitive.
- **Other languages.** `--locale de_DE` makes names and addresses German.
  States are always US states.
