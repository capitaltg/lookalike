"""Named option profiles stored in a TOML config file.

    [customers]
    drop = ["ssn"]

    [customers.types]
    col7 = "name"
    employee_no = 'regex:EMP\\d{6}'

A profile holds option values only (column names, types, flags), never data.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

LOCAL_NAME = "lookalike.toml"
ENV_VAR = "LOOKALIKE_CONFIG"

LIST_KEYS = ("keep", "drop", "null_values")
BOOL_KEYS = ("no_null_tokens", "preserve_order", "shuffle_rows")
STR_KEYS = ("format", "delimiter", "locale")
KEYS = LIST_KEYS + BOOL_KEYS + STR_KEYS + ("types",)

_NAME = re.compile(r"[A-Za-z0-9_-]+")


def user_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "lookalike" / "config.toml"


def find(explicit: str | None = None, for_write: bool = False) -> Path | None:
    """The config file in use: --config, $LOOKALIKE_CONFIG, ./lookalike.toml, then the user file.

    A file named explicitly need not exist when writing; when reading it must.
    """
    named = explicit or os.environ.get(ENV_VAR)
    if named:
        p = Path(named)
        if not for_write and not p.is_file():
            raise ValueError(f"config file not found: {p}")
        return p
    local = Path(LOCAL_NAME)
    if local.is_file():
        return local
    user = user_path()
    return user if for_write or user.is_file() else None


def _parse(text: str, path: Path) -> dict[str, dict]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: not valid TOML: {e}") from None
    for name, prof in data.items():
        if not isinstance(prof, dict):
            raise ValueError(f"{path}: {name!r} is not inside a [profile] section")
        _validate(prof, f"{path}: profile [{name}]")
    return data


def _validate(prof: dict, where: str) -> None:
    for k, v in prof.items():
        if k not in KEYS:
            raise ValueError(f"{where}: unknown setting {k!r}; choose from {', '.join(KEYS)}")
        if k in LIST_KEYS:
            ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
            want = "a list of strings"
        elif k in BOOL_KEYS:
            ok, want = isinstance(v, bool), "true or false"
        elif k in STR_KEYS:
            ok, want = isinstance(v, str), "a string"
        else:
            ok = isinstance(v, dict) and all(isinstance(x, str) for x in v.values())
            want = 'a table of COLUMN = "TYPE"'
        if not ok:
            raise ValueError(f"{where}: {k} must be {want}")


def load_all(path: Path) -> dict[str, dict]:
    return _parse(path.read_text(encoding="utf-8"), path)


def load_profile(name: str, explicit: str | None = None) -> dict:
    path = find(explicit)
    if path is None:
        raise ValueError(
            f"no config file for profile {name!r}: looked for ./{LOCAL_NAME} and {user_path()} "
            f"(or pass --config FILE)"
        )
    profiles = load_all(path)
    if name not in profiles:
        have = ", ".join(profiles) or "none"
        raise ValueError(f"{path}: no profile [{name}] (profiles: {have})")
    return profiles[name]


def _s(v: str) -> str:
    """A TOML string; the literal form keeps regex backslashes readable."""
    if all(c.isprintable() for c in v):
        if "\\" not in v and '"' not in v:
            return f'"{v}"'
        if "'" not in v:
            return f"'{v}'"
    out = json.dumps(v, ensure_ascii=False)
    # JSON leaves these raw, TOML forbids them in basic strings
    return re.sub(r"[\x7f  ]", lambda m: f"\\u{ord(m.group()):04x}", out)


def render(name: str, prof: dict) -> str:
    head = name if _NAME.fullmatch(name) else _s(name)  # hand-written names may need quoting
    lines = [f"[{head}]"]
    for k in KEYS:
        if k not in prof or k == "types":
            continue
        v = prof[k]
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, list):
            lines.append(f"{k} = [{', '.join(_s(x) for x in v)}]")
        else:
            lines.append(f"{k} = {_s(v)}")
    if prof.get("types"):
        lines += ["", f"[{head}.types]"]
        for col, typ in prof["types"].items():
            key = col if _NAME.fullmatch(col) else _s(col)
            lines.append(f"{key} = {_s(typ)}")
    return "\n".join(lines) + "\n"


def save_profile(name: str, prof: dict, explicit: str | None = None) -> Path:
    """Append a new profile to the config file, leaving the rest of the file untouched."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"profile name {name!r} may only use letters, digits, - and _")
    if not prof:
        raise ValueError("nothing to save: give at least one option, e.g. --type COLUMN=TYPE")
    _validate(prof, f"profile [{name}]")
    path = find(explicit, for_write=True)
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    if name in _parse(old, path):
        raise ValueError(f"{path}: profile [{name}] already exists; edit the file or pick another name")
    new = old + ("" if not old or old.endswith("\n") else "\n") + ("\n" if old else "") + render(name, prof)
    if _parse(new, path).get(name) != prof:  # what was written must read back as what was asked
        raise RuntimeError(f"could not write profile [{name}] faithfully; {path} was not changed")
    try:
        raw = new.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"profile [{name}] contains text that is not valid Unicode; nothing was saved") from None
    # Write beside the file and swap it in, so a failure cannot damage what is there.
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.resolve()  # follow a symlinked config instead of replacing the link
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")  # unique, created exclusively
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path
