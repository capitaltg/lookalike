"""Random strings that match a user-supplied regular expression.

Used by the ``regex:PATTERN`` column type. The pattern is parsed with the
standard library's own regex parser and every generated string is checked with
``re.fullmatch`` before it is returned, so output always matches the pattern.
"""

from __future__ import annotations

import re
import string

try:  # Python 3.11+
    from re import _constants as _c
    from re import _parser as _p
except ImportError:  # pragma: no cover - Python 3.10
    import sre_constants as _c
    import sre_parse as _p

# Characters used for ".", negated classes such as [^0-9] and \D, \W, \S.
ALPHABET = string.ascii_letters + string.digits + string.punctuation + " "
_WORD = string.ascii_letters + string.digits + "_"
# Open-ended repeats (*, +, {2,}) produce at most this many items beyond the minimum.
MAX_EXTRA = 8
_SIZE_CAP = 10**30
# Longest value a pattern may produce. Keeps generation and the fullmatch check cheap.
MAX_LENGTH = 1000
_RANGE_CAP = 4096

_CATEGORIES = {
    _c.CATEGORY_DIGIT: string.digits,
    _c.CATEGORY_NOT_DIGIT: "".join(c for c in ALPHABET if c not in string.digits),
    _c.CATEGORY_WORD: _WORD,
    _c.CATEGORY_NOT_WORD: "".join(c for c in ALPHABET if c not in _WORD),
    _c.CATEGORY_SPACE: " ",
    _c.CATEGORY_NOT_SPACE: "".join(c for c in ALPHABET if c != " "),
}
_REPEATS = {_c.MAX_REPEAT, _c.MIN_REPEAT} | ({_c.POSSESSIVE_REPEAT} if hasattr(_c, "POSSESSIVE_REPEAT") else set())


class RegexGen:
    """Generator for one pattern. Raises ``ValueError`` for patterns it cannot serve."""

    def __init__(self, pattern: str):
        self.pattern = pattern
        try:
            self.rx = re.compile(pattern)
            self.node = self._seq(_p.parse(pattern))
            longest = self._max_len(self.node)
        except (re.error, OverflowError) as e:
            raise ValueError(f"invalid regular expression {pattern!r}: {e}") from e
        except RecursionError as e:
            raise ValueError(f"regular expression {pattern!r} is nested too deeply") from e
        if longest > MAX_LENGTH:
            raise ValueError(
                f"regular expression {pattern!r} can produce values longer than {MAX_LENGTH} "
                "characters; use smaller repeat counts"
            )

    # -- compile the parse tree into ("chars", str) / ("seq", [...]) / ("alt", [...]) / ("rep", lo, hi, node)
    def _unsupported(self, what: str):
        return ValueError(f"regular expression {self.pattern!r}: {what} is not supported for generating values")

    def _seq(self, items):
        return ("seq", [n for n in (self._node(op, av) for op, av in items) if n is not None])

    def _node(self, op, av):
        if op is _c.LITERAL:
            return ("chars", chr(av))
        if op is _c.NOT_LITERAL:
            return ("chars", "".join(c for c in ALPHABET if c != chr(av)))
        if op is _c.ANY:
            return ("chars", string.ascii_letters + string.digits)
        if op is _c.IN:
            return ("chars", self._charset(av))
        if op in _REPEATS:
            lo, hi, sub = av
            if lo > MAX_LENGTH or (hi is not _c.MAXREPEAT and hi > MAX_LENGTH):
                # Also covers repeats of an empty group, which add no length but
                # still cost the regex engine one step per repetition.
                raise ValueError(
                    f"regular expression {self.pattern!r}: repeat counts above {MAX_LENGTH} are not supported"
                )
            if hi is _c.MAXREPEAT:
                hi = lo + MAX_EXTRA
            inner = self._seq(sub)
            if self._max_len(inner) == 0:
                return None  # repeating nothing adds nothing; never loop over it
            return ("rep", lo, hi, inner)
        if op is _c.SUBPATTERN:
            return self._seq(av[-1])
        if hasattr(_c, "ATOMIC_GROUP") and op is _c.ATOMIC_GROUP:
            return self._seq(av)
        if op is _c.BRANCH:
            return ("alt", [self._seq(branch) for branch in av[1]])
        if op is _c.AT:
            return None  # anchors add no characters; fullmatch re-checks them
        if op in (_c.GROUPREF, _c.GROUPREF_EXISTS):
            raise self._unsupported("a back-reference")
        if op in (_c.ASSERT, _c.ASSERT_NOT):
            raise self._unsupported("a look-ahead or look-behind")
        raise self._unsupported(f"the construct {op}")

    def _charset(self, items) -> str:
        negate = False
        chars: set[str] = set()
        for op, av in items:
            if op is _c.NEGATE:
                negate = True
            elif op is _c.LITERAL:
                chars.add(chr(av))
            elif op is _c.RANGE:
                lo, hi = av
                chars.update(chr(i) for i in range(lo, min(hi, lo + _RANGE_CAP) + 1))
            elif op is _c.CATEGORY:
                if av not in _CATEGORIES:
                    raise self._unsupported(f"the character class {av}")
                chars.update(_CATEGORIES[av])
            else:
                raise self._unsupported(f"the construct {op}")
        if negate:
            chars = set(ALPHABET) - chars
        if not chars:
            raise self._unsupported("a character class with nothing to choose from")
        return "".join(sorted(chars))

    # -- how many different strings the pattern can produce (an upper bound, capped)
    def size(self) -> int:
        return self._size(self.node)

    def _size(self, node) -> int:
        kind = node[0]
        if kind == "chars":
            return len(node[1])
        if kind == "seq":
            total = 1
            for n in node[1]:
                total = min(_SIZE_CAP, total * self._size(n))
            return total
        if kind == "alt":
            return min(_SIZE_CAP, sum(self._size(n) for n in node[1]))
        _, lo, hi, sub = node
        base = self._size(sub)
        if base <= 1:
            return hi - lo + 1 if base == 1 else 1
        if lo > 100:  # base >= 2, so base**lo is already beyond the cap
            return _SIZE_CAP
        total = 0
        for k in range(lo, hi + 1):
            total += base**k
            if total >= _SIZE_CAP:
                return _SIZE_CAP
        return total

    def _max_len(self, node) -> int:
        """Length of the longest string the pattern can produce (stops counting past the limit)."""
        kind = node[0]
        if kind == "chars":
            return 1
        if kind == "seq":
            total = 0
            for n in node[1]:
                total += self._max_len(n)
                if total > MAX_LENGTH:
                    break
            return total
        if kind == "alt":
            return max((self._max_len(n) for n in node[1]), default=0)
        return min(node[2] * self._max_len(node[3]), MAX_LENGTH + 1)

    # -- generation
    def make(self, rng) -> str:
        for _ in range(50):
            out: list[str] = []
            self._emit(self.node, rng, out)
            s = "".join(out)
            if self.rx.fullmatch(s):
                return s
        raise ValueError(f"could not generate a value matching {self.pattern!r}")

    def _emit(self, node, rng, out: list[str]) -> None:
        kind = node[0]
        if kind == "chars":
            out.append(rng.choice(node[1]))
        elif kind == "seq":
            for n in node[1]:
                self._emit(n, rng, out)
        elif kind == "alt":
            self._emit(rng.choice(node[1]), rng, out)
        else:
            _, lo, hi, sub = node
            for _ in range(rng.randint(lo, hi)):
                self._emit(sub, rng, out)
