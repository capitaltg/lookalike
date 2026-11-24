# lookalike

Turn a data file full of real people into one that looks the same but isn't.

`lookalike` replaces every value in a CSV, JSON, JSON Lines or Parquet file
with random fake data of the same type and shape. Each column keeps its number
of distinct values and how often each one occurs, so the copy behaves like the
original in tests, demos and analysis. Before the output is saved it is checked
against the input; if any original value survived, nothing is written.

## Example

Input (`examples/customers.csv`):

```
customer_id,full_name,email,phone,ssn,city,state,...
CU-1001,Maria Lopez,maria.lopez@acme.com,(703) 281-4410,514-22-9081,Reston,VA,...
CU-1002,James Carter,jcarter@gmail.com,(301) 774-2295,233-71-4406,Bethesda,MD,...
CU-1003,Priya Nair,priya.nair@acme.com,(571) 902-1184,601-35-7720,Reston,VA,...
CU-1001,Maria Lopez,maria.lopez@acme.com,(703) 281-4410,514-22-9081,Reston,VA,...
```

Output:

```
customer_id,full_name,email,phone,ssn,city,state,...
ZO-7893,Scott Kirby,hartdaniel298@ikuma.example,(249) 555-4032,000-62-2439,West Jasonborough,DC,...
WO-9217,April Bowman,ojones692@bajecoro.example,(899) 555-1023,000-32-8367,North Josephmouth,CO,...
DU-0967,Vincent Bates,matthew45420@ikuma.example,(940) 555-9546,000-60-1108,West Jasonborough,DC,...
ZO-7893,Scott Kirby,hartdaniel298@ikuma.example,(249) 555-4032,000-62-2439,West Jasonborough,DC,...
```

Rows 1 and 4 were the same customer and still are. The two `acme.com`
addresses still share a domain. Nothing real is left.

## Install

Requires Python 3.10 or newer.

```
pip install lookalike
```

For Parquet files, install with the extra:

```
pip install "lookalike[parquet]"
```

## Use

```
lookalike inspect   customers.csv                  # 1. see how each column will be treated
lookalike anonymize customers.csv safe.csv         # 2. write the anonymized copy
lookalike verify    customers.csv safe.csv         # 3. optional: re-check later
```

Common adjustments. `ssn`, `notes`, `order_total` and `col7` below stand for
column names in your own file; `inspect` lists them.

```
lookalike anonymize in.csv out.csv --drop ssn --drop notes     # remove the ssn and notes columns
lookalike anonymize in.csv out.csv --keep order_total          # leave the order_total column as is
lookalike anonymize in.csv out.csv --type col7=name            # tell it the col7 column holds people's names
lookalike anonymize in.csv out.csv --type 'code=regex:[0-9]{2}-[A-Z]{5}'   # fill the code column from your own pattern
lookalike anonymize in.csv out.csv --report report.json        # save the check results
```

`--type` takes `COLUMN=TYPE`. Every column is anonymized whatever its type;
the type only decides what the fakes look like. A column of names that
`inspect` shows as `text` would come out as `Kovar Tunib`; with
`--type col7=name` it comes out as `Scott Kirby`. For a format of your own,
use `regex:` followed by a regular expression: `[0-9]{2}-[A-Z]{5}` gives values
such as `66-QNIDO`. The full list of types is in
[Column types](docs/column-types.md).

To reuse the same options, save them under a name and pass `--profile`
(see [Profiles](docs/cli.md#profiles)):

```
lookalike profile save customers --drop ssn --type col7=name
lookalike anonymize in.csv out.csv --profile customers
```

Exit code `0` means the output was written and passed every check.

## Before you share the output

`lookalike` removes the values, not the patterns. Someone looking at the
output can still see how many distinct values a column has, how often each
occurs, where the blanks are, and the rough range of numbers and dates. That
is the point of the tool, but it also means a person who already knows your
data could recognise rows by their pattern. Drop columns you do not need, and
read [what is and is not guaranteed](docs/privacy.md) before publishing
anything.

## Documentation

| Guide | What it covers |
|---|---|
| [Getting started](docs/getting-started.md) | A first run, step by step, and how to read the results |
| [Command reference](docs/cli.md) | Every command and option, selecting columns, exit codes |
| [Column types](docs/column-types.md) | How types are detected and what each fake looks like |
| [Privacy guarantees](docs/privacy.md) | What is protected, what stays visible, known limits |
| [Verification](docs/verification.md) | The checks that run and the fields of the report |
| [File formats](docs/formats.md) | CSV, JSON, JSON Lines and Parquet specifics |
| [Python API](docs/python-api.md) | Using `lookalike` from code |

## Development

```
uv sync
uv run pytest
```

Pushing a `vX.Y.Z` tag publishes to PyPI; see [Releasing](docs/releasing.md).
