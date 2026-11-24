import csv
import json
import random
from collections import Counter

import pytest

from lookalike import Options, anonymize, load, make_plans, verify
from lookalike.cli import main
from lookalike.core import null_test, selector
from lookalike.detect import infer

FIRST = ["Ann", "Bob", "Cara", "Dev", "Eli", "Fay", "Gus", "Hana"]
LAST = ["Smith", "Jones", "Nguyen", "Garcia", "Okafor", "Kim"]
STATES = ["VA", "MD", "DC", "NY"]


def make_csv(path, n=300, seed=1):
    r = random.Random(seed)
    people = []
    for i in range(60):
        fn, ln = r.choice(FIRST), r.choice(LAST)
        people.append({
            "customer_id": f"CU-{1000 + i}",
            "first_name": fn,
            "last_name": ln,
            "email": f"{fn.lower()}.{ln.lower()}{i}@{r.choice(['acme.com', 'gmail.com'])}",
            "phone": f"({r.randint(200, 999)}) {r.randint(200, 999)}-{r.randint(0, 9999):04d}",
            "ssn": f"{r.randint(100, 899)}-{r.randint(10, 99)}-{r.randint(1000, 9999)}",
            "street_address": f"{r.randint(1, 999)} {r.choice(['Oak', 'Main', 'Elm'])} St",
            "city": r.choice(["Reston", "Bethesda", "Arlington"]),
            "state": r.choice(STATES),
            "zip": f"{r.randint(10000, 99999)}",
            "dob": f"{r.randint(1950, 2000)}-{r.randint(1, 12):02d}-{r.randint(1, 28):02d}",
        })  # fmt: skip
    rows = []
    for i in range(n):
        p = dict(r.choice(people))
        p.update({
            "order_id": str(i + 1),
            "amount": f"{r.uniform(5, 500):.2f}",
            "active": r.choice(["true", "false"]),
            "status": r.choice(["shipped", "pending", "cancelled"]),
            "notes": r.choice(["", "", "call back", "NA"]),
            "created_at": f"2024-{r.randint(1, 12):02d}-{r.randint(1, 28):02d}T{r.randint(0, 23):02d}:15:00Z",
        })  # fmt: skip
        rows.append(p)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_csv_end_to_end(tmp_path):
    src, dst, rep = tmp_path / "in.csv", tmp_path / "out.csv", tmp_path / "report.json"
    rows = make_csv(src)
    assert main(["anonymize", str(src), str(dst), "--report", str(rep)]) == 0
    out = read_csv(dst)
    assert len(out) == len(rows) and list(out[0]) == list(rows[0])
    report = json.loads(rep.read_text())
    assert report["passed"]
    for col in rows[0]:
        a = [r[col] for r in rows]
        b = [r[col] for r in out]
        # same cardinality and same frequency distribution
        assert len(set(a)) == len(set(b)), col
        assert sorted(Counter(a).values()) == sorted(Counter(b).values()), col
        # equality pattern preserved row by row
        assert len(set(zip(a, b))) == len(set(a)), col
        if col in ("active",):
            continue
        for x, y in zip(a, b):
            if x in ("", "NA"):
                assert y == x
            else:
                assert x != y, col
        if col not in ("state", "amount", "order_id", "dob", "created_at"):
            assert not ({v for v in a if v not in ("", "NA")} & set(b)), col
    # the report must not contain any data value
    text = rep.read_text()
    for r in rows:
        assert r["email"] not in text and r["ssn"] not in text


def test_types_detected_and_shapes_kept(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    make_csv(src)
    plans = make_plans(load(src).records, Options())
    got = {p: pl.type for p, pl in plans.items()}
    assert got == {
        "customer_id": "text", "first_name": "first_name", "last_name": "last_name",
        "email": "email", "phone": "phone", "ssn": "ssn", "street_address": "street",
        "city": "city", "state": "state", "zip": "zip", "dob": "date", "order_id": "int",
        "amount": "float", "active": "bool", "status": "text", "notes": "text",
        "created_at": "datetime",
    }  # fmt: skip
    assert main(["anonymize", str(src), str(dst), "--seed", "7"]) == 0
    import re

    for r in read_csv(dst):
        assert re.fullmatch(r"[A-Z]{2}-\d{4}", r["customer_id"])
        assert re.fullmatch(r"[^@]+@[a-z]+\.example", r["email"])
        assert re.fullmatch(r"\(\d{3}\) 555-\d{4}", r["phone"])
        assert re.fullmatch(r"(000|666)-\d{2}-\d{4}", r["ssn"])
        assert re.fullmatch(r"\d{5}", r["zip"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["dob"])
        assert re.fullmatch(r"\d+\.\d{2}", r["amount"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", r["created_at"])
        assert re.fullmatch(r"[A-Z]{2}", r["state"])
        assert r["active"] in ("true", "false")


def test_seed_is_reproducible_and_default_is_not(tmp_path):
    src = tmp_path / "in.csv"
    make_csv(src, n=50)
    outs = []
    for name, extra in (("a", ["--seed", "3"]), ("b", ["--seed", "3"]), ("c", [])):
        dst = tmp_path / f"{name}.csv"
        assert main(["anonymize", str(src), str(dst), *extra]) == 0
        outs.append(dst.read_text())
    assert outs[0] == outs[1] != outs[2]


def test_nested_json_keep_drop(tmp_path):
    data = [
        {
            "id": i,
            "name": f"Person {i % 4}",
            "ratio": i / 8,
            "vip": i % 2 == 0,
            "secret": "x",
            "tags": ["a", "b"] if i % 2 else [],
            "contact": {"email": f"p{i % 4}@corp.com", "phones": [f"703-555-{1000 + i}", None]},
            "region": "east",
        }
        for i in range(20)
    ]
    src, dst = tmp_path / "in.json", tmp_path / "out.json"
    src.write_text(json.dumps(data))
    assert main(["anonymize", str(src), str(dst), "--keep", "region", "--drop", "secret"]) == 0
    out = json.loads(dst.read_text())
    assert len(out) == 20
    for o, a in zip(data, out):
        assert "secret" not in a and a["region"] == "east"
        assert isinstance(a["id"], int) and isinstance(a["ratio"], float) and isinstance(a["vip"], bool)
        assert a["contact"]["phones"][1] is None
        assert len(a["tags"]) == len(o["tags"])
        assert a["contact"]["email"] != o["contact"]["email"]
    assert len({a["name"] for a in out}) == 4
    assert len({a["contact"]["email"] for a in out}) == 4
    assert len({a["contact"]["email"].split("@")[1] for a in out}) == 1
    assert len({a["id"] for a in out}) == 20


def test_jsonl_and_shuffle(tmp_path):
    src, dst = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    rows = [{"user": f"u{i}", "score": i % 5} for i in range(40)]
    src.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert main(["anonymize", str(src), str(dst), "--shuffle-rows"]) == 0
    out = [json.loads(line) for line in dst.read_text().splitlines()]
    assert len({r["user"] for r in out}) == 40 and len({r["score"] for r in out}) == 5
    assert main(["verify", str(src), str(dst), "--unordered"]) == 0


def test_verify_catches_problems(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    rows = make_csv(src, n=40)
    # an unmodified copy is not anonymized
    assert main(["verify", str(src), str(src)]) == 2
    assert main(["anonymize", str(src), str(dst)]) == 0
    assert main(["verify", str(src), str(dst)]) == 0
    # leak one original value back into the output
    out = read_csv(dst)
    out[3]["email"] = rows[3]["email"]
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    assert main(["verify", str(src), str(dst)]) == 2


def test_failed_verification_writes_nothing(tmp_path, monkeypatch):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    make_csv(src, n=20)
    import lookalike.cli as cli

    monkeypatch.setattr(cli, "anonymize", lambda recs, opts: (recs, make_plans(recs, opts), None))
    assert main(["anonymize", str(src), str(dst)]) == 2
    assert not dst.exists() and not list(tmp_path.glob("*.unverified"))


def test_saturated_domains_and_order():
    # every single-digit code and every letter is used: domain must grow, not loop
    recs = [{"code": str(i % 10), "letter": "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i % 26], "n": i} for i in range(260)]
    out, plans, _ = anonymize(recs, Options(seed=1, preserve_order=True))
    rep = verify(recs, out, plans, null_test(Options().null_values))
    assert rep["passed"], rep["issues"]
    assert len({r["letter"] for r in out}) == 26
    pairs = sorted((o["n"], a["n"]) for o, a in zip(recs, out))
    assert [a for _, a in pairs] == sorted(a for _, a in pairs)


def test_mixed_and_odd_values():
    recs = [
        {"v": 1, "w": "2024-01-05", "x": "1.50", "y": "007"},
        {"v": 1.0, "w": "not a date", "x": "2.5", "y": "12"},
        {"v": True, "w": "2024-01-06", "x": "1e3", "y": "NA"},
        {"v": "1", "w": None, "x": "", "y": "x"},
    ]
    out, plans, _ = anonymize(recs, Options(seed=2))
    rep = verify(recs, out, plans, null_test(Options().null_values))
    assert rep["passed"], rep["issues"]
    assert out[2]["y"] == "NA" and out[3]["w"] is None and out[3]["x"] == ""
    assert [type(r["v"]) for r in out] == [int, float, bool, str]


def test_selector_and_infer():
    s = selector(["a.b", "tags[]", "x*"])
    assert s("a.b") and s("a.b.c") and s("a.b[].c") and s("tags[]") and s("xyz")
    assert not s("a.bc") and not s("tags")
    assert infer("contactEmail", ["a@b.co", "c@d.org"])[0] == "email"
    assert infer("id", ["3f2b8c1e-1111-4222-8333-123456789abc"])[0] == "uuid"
    assert infer("Mobile Phone", ["7035551234"])[0] == "phone"
    assert infer("state", ["active", "closed"])[0] == "text"
    assert infer("visit", ["03/15/2024", "12/01/2023"]) == ("date", "%m/%d/%Y")


def test_parquet_roundtrip(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import datetime as dt

    import pyarrow.parquet as pq

    src, dst = tmp_path / "in.parquet", tmp_path / "out.parquet"
    table = pa.table({
        "id": pa.array(range(30), pa.int64()),
        "email": [f"u{i % 7}@x.org" for i in range(30)],
        "born": [dt.date(1990, 1, 1) + dt.timedelta(days=i % 9) for i in range(30)],
        "seen": [dt.datetime(2024, 1, 1, 12) + dt.timedelta(hours=i) for i in range(30)],
        "amt": [float(i % 5) + 0.25 for i in range(30)],
        "ok": [i % 3 == 0 for i in range(30)],
    })  # fmt: skip
    pq.write_table(table, src)
    assert main(["anonymize", str(src), str(dst)]) == 0
    out = pq.read_table(dst)
    assert out.schema.equals(table.schema)
    assert len(set(out["email"].to_pylist())) == 7
    assert len(set(out["born"].to_pylist())) == 9
    assert not set(out["email"].to_pylist()) & set(table["email"].to_pylist())


NULLS = null_test(Options().null_values)


def run(recs, **kw):
    out, plans, _ = anonymize(recs, Options(seed=1, **kw))
    return out, verify(recs, out, plans, NULLS)


def test_review_symbols_and_schemes_do_not_survive():
    out, rep = run([{"v": "🔑🧬"}, {"v": "---"}, {"v": "a🔑b"}])
    assert rep["passed"]
    assert all("🔑" not in r["v"] and r["v"] != "---" for r in out)
    out, rep = run([{"v": "alice-secret://private/path"}], types={"v": "url"})
    assert "alice" not in out[0]["v"] and rep["passed"]


def test_review_verifier_blind_spots():
    plans = make_plans([{"v": 12345}], Options())
    assert not verify([{"v": 12345}], [{"v": "12345"}], plans, NULLS)["passed"]
    assert not verify([{"v": 12345}], [{"v": 12345.0}], plans, NULLS)["passed"]
    o = [{"v": "ALICE"}]
    plans = make_plans(o, Options(types={"v": "bool"}))
    assert not verify(o, o, plans, NULLS)["passed"]
    plans = make_plans(o, Options())
    assert not verify(o, [{"v": "CAROL", "ALICE": {}}], plans, NULLS)["passed"]
    o = [{"v": [["ALICE"], ["BOB"]]}]
    assert not verify(o, [{"v": [["CAROL", "DAVID"]]}], make_plans(o, Options()), NULLS)["passed"]
    o = [{"v": "NA"}, {"v": "None"}]
    assert not verify(o, [{"v": "NA"}, {"v": "NA"}], make_plans(o, Options()), NULLS, aligned=False)["passed"]


def test_review_null_tokens_warn_and_can_be_disabled():
    recs = [{"code": "NA"}, {"code": "None"}, {"code": "N/A"}]
    out, rep = run(recs)
    assert out == recs and any("null token" in w for w in rep["warnings"])
    out, plans, _ = anonymize(recs, Options(seed=1, null_values=()))
    assert all(a["code"] != o["code"] for a, o in zip(out, recs))


def test_review_bool_case_and_order_and_floats():
    out, rep = run([{"v": "true"}, {"v": "tRuE"}, {"v": "false"}])
    assert rep["passed"], rep["issues"]
    for seed in range(40):
        recs = [{"v": 5}, {"v": 6}, {"v": 7}]
        out, _, _ = anonymize(recs, Options(seed=seed, preserve_order=True))
        vals = [r["v"] for r in out]
        assert vals == sorted(vals) and len(set(vals)) == 3
    out, rep = run([{"v": 1e308}, {"v": 1e-100}, {"v": 2.5}])
    assert rep["passed"], rep["issues"]
    out, rep = run([{"v": 1e-100}, {"v": 3e-100}])
    assert rep["passed"] and all(0 < r["v"] < 1e-90 for r in out)


def test_review_csv_quirks(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text('"a;b;c",x\nALICE,BOB\nCAROL,DAN\n')
    assert load(src).meta["names"] == ["a;b;c", "x"]
    src.write_text("x,x,\nALICE,BOB,C1\nCAROL,DAN,C2\n")
    assert main(["anonymize", str(src), str(dst), "--drop", "x"]) == 0
    assert dst.read_text().splitlines()[0] == "x,"
    assert main(["verify", str(src), str(dst), "--drop", "x"]) == 0
    assert main(["anonymize", str(src), str(dst), "--report", str(src)]) == 1
    assert src.read_text().startswith("x,x,")


def test_review_parquet_int_bounds(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    src, dst = tmp_path / "in.parquet", tmp_path / "out.parquet"
    pq.write_table(pa.table({"a": pa.array([127, 126, 5], pa.int8()), "b": pa.array([2**64 - 1, 1, 2], pa.uint64())}), src)
    assert main(["anonymize", str(src), str(dst)]) == 0
    assert pq.read_table(dst).schema.equals(pq.read_table(src).schema)


def test_review_round_two(tmp_path):
    out, rep = run([{"v": "---"}], types={"v": "hex"})
    assert rep["passed"] and "---" not in out[0]["v"]
    recs = [{"v": 12345}, {"v": 67890.0}]
    assert not verify(recs, [{"v": 12345.0}, {"v": 67890}], make_plans(recs, Options()), NULLS)["passed"]
    out, rep = run([{"v": 1.7976931348623157e308}])
    assert rep["passed"]
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("a,b\nALICE,BOB\n")
    b.write_text("ALICE,b\nCAROL,DAVID\n")
    assert main(["verify", str(a), str(b)]) == 2
    a.write_text("a;b\nALICE\nBOB;CAROL\n")
    assert load(a).meta["names"] == ["a", "b"]


def test_regex_type(tmp_path):
    import re

    from lookalike.regexgen import RegexGen

    rng = random.Random(0)
    for pat in [r"[0-9]{2}-[A-Z]{5}", r"(INV|PO)-\d{4,6}", r"[^0-9]\w+\s?x*", r"^a.c$", r"\d{3}=[a-f]{2}", r"(?:ab|c){2,3}"]:
        g = RegexGen(pat)
        assert all(re.fullmatch(pat, g.make(rng)) for _ in range(200)), pat
    assert RegexGen(r"[0-9]{2}-[A-Z]{5}").size() == 100 * 26**5
    assert RegexGen(r"(a|bc)?x").size() == 3
    for bad in [r"(a)\1", r"a(?=b)", r"[a", r"(?<!x)y"]:
        with pytest.raises(ValueError):
            RegexGen(bad)

    pat = r"[0-9]{2}-[A-Z]{5}"
    recs = [{"code": f"legacy {i % 30}", "n": i} for i in range(90)]
    opts = Options(seed=3, types={"code": "regex:" + pat})
    out, plans, _ = anonymize(recs, opts)
    assert plans["code"].type == "regex" and plans["code"].fmt == pat
    assert all(re.fullmatch(pat, r["code"]) for r in out)
    assert len({r["code"] for r in out}) == 30
    rep = verify(recs, out, plans, NULLS)
    assert rep["passed"] and rep["columns"]["code"]["pattern_mismatches"] == 0
    out[0]["code"] = "nope"
    assert not verify(recs, out, plans, NULLS)["passed"]

    # too narrow a pattern is an error, not a silent format break
    with pytest.raises(RuntimeError, match="code"):
        anonymize(recs, Options(seed=1, types={"code": "regex:[A-C]"}))
    # originals already matching the pattern are never reused
    recs = [{"c": x} for x in "ABCDEFGHIJ"]
    out, plans, _ = anonymize(recs, Options(seed=1, types={"c": "regex:[A-Z]"}))
    assert not {r["c"] for r in out} & set("ABCDEFGHIJ")
    with pytest.raises(ValueError):
        make_plans(recs, Options(types={"c": "regex:(a)\\1"}))

    # command line: a pattern containing "=" and a column whose values vary in shape
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text("id,code\n1,x\n2,yy\n3,x\n")
    assert main(["anonymize", str(src), str(dst), "--type", r"code=regex:K=\d{3}"]) == 0
    rows = read_csv(dst)
    assert all(re.fullmatch(r"K=\d{3}", r["code"]) for r in rows) and rows[0]["code"] == rows[2]["code"]
    assert main(["verify", str(src), str(dst), "--type", r"code=regex:K=\d{3}"]) == 0
    assert main(["anonymize", str(src), str(dst), "--type", "code=regex:[a"]) == 1


def test_regex_review_fixes(tmp_path):
    import time

    from lookalike.regexgen import RegexGen

    t = time.time()
    for bad in ["[a-z]{1000000000}", "(?:a{100000}){100000}", "a{0,10001}", "(" * 350 + "a" + ")" * 350]:
        with pytest.raises(ValueError):
            RegexGen(bad)
    assert RegexGen("[a-z]{900}").size() == 10**30
    assert RegexGen(r"(?:(?:){100000}){100000}[A-Z]").make(random.Random(0)).isupper()
    assert RegexGen("a{0,900}").size() == 901
    assert time.time() - t < 2
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text("a=b,n\nx,1\ny,2\n")
    assert main(["anonymize", str(src), str(dst), "--type", "a=b=regex:[A-Z]{3}=[0-9]"]) == 0
    import re

    assert all(re.fullmatch("[A-Z]{3}=[0-9]", r["a=b"]) for r in read_csv(dst))
