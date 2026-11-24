"""Random fake value generators.

Every generator takes the original string only to copy its *shape* (length,
case, punctuation layout, digit count). The content always comes from the RNG.
"""

from __future__ import annotations

import re
import string
import uuid
from typing import Callable

from faker import Faker
from faker.providers import BaseProvider
from faker.providers.address.en_US import Provider as _US

_CONS = "bcdfghjklmnprstvwz"
_VOW = "aeiou"
_TOKEN = re.compile(r"[^\W\d_]+|\d+|[\W_]+")
_IPV4 = re.compile(r"(\d{1,3}\.){3}\d{1,3}")
_HEXCH = "0123456789abcdef"
_LAYOUT = set(string.punctuation + " \t\r\n")
_SCHEMES = {"http", "https", "ftp", "ftps", "sftp", "ws", "wss", "s3", "file"}
# Faker picks street suffixes uniformly from the ~225 USPS ones, so most fakes
# end in "Trace" or "Stravenue". Draw mostly from the ones people recognise.
_COMMON_SUFFIXES = {
    "Street": 30, "Avenue": 16, "Road": 14, "Drive": 14, "Lane": 8, "Court": 6,
    "Boulevard": 4, "Way": 4, "Place": 4, "Circle": 3, "Terrace": 2, "Parkway": 2,
    "Trail": 2, "Highway": 1,
}
_RARE_SUFFIX_RATE = 0.03


def _luhn(body: str) -> str:
    total = 0
    for i, c in enumerate(reversed(body)):
        d = int(c)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


class Fakes:
    def __init__(self, rng, locale: str = "en_US"):
        self.rng = rng
        self.f = Faker(locale)
        self.f.random = rng
        self._domains: dict[str, str] = {}
        self._weight_suffixes()
        self.GENERATORS: dict[str, Callable[[str], str]] = {
            "text": self.scramble,
            "zip": self.scramble,
            "first_name": lambda o: self._case(o, self.f.first_name()),
            "last_name": lambda o: self._case(o, self.f.last_name()),
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "ssn": self.ssn,
            "credit_card": self.credit_card,
            "ipv4": self.ipv4,
            "uuid": self.uuid,
            "hex": self.hex,
            "mac": self.hex,
            "url": self.url,
            "street": lambda o: self._case(o, self.f.street_address()),
            "address": lambda o: self._case(o, self.f.address().replace("\n", ", ")),
            "address2": lambda o: self._case(o, self.f.secondary_address()),
            "city": lambda o: self._case(o, self.f.city()),
            "company": lambda o: self._case(o, self.f.company()),
            "username": lambda o: self._case(o, self.f.user_name()),
            "state": self.state,
            "country": self.country,
        }

    def _weight_suffixes(self) -> None:
        """Make the locale's common street suffixes the likely ones.

        Only applies where the locale's own list has them (English locales);
        others keep Faker's behaviour.
        """
        # list(): some locales (en_PH) keep the suffixes as a weighted mapping.
        pool = list(next(
            (p.street_suffixes for p in self.f.get_providers() if hasattr(p, "street_suffixes")),
            (),
        ))
        common = [s for s in _COMMON_SUFFIXES if s in pool]
        if len(common) < 5:
            return
        weights = [_COMMON_SUFFIXES[s] for s in common]
        rng = self.rng

        class _Suffix(BaseProvider):
            def street_suffix(self) -> str:
                if rng.random() < _RARE_SUFFIX_RATE:
                    return rng.choice(pool)
                return rng.choices(common, weights)[0]

        self.f.add_provider(_Suffix)

    def new_column(self) -> None:
        """Forget per-column state (the email domain mapping)."""
        self._domains = {}

    # -- building blocks -------------------------------------------------
    @staticmethod
    def _case(orig: str, s: str) -> str:
        if orig.isupper():
            return s.upper()
        if orig.islower():
            return s.lower()
        return s

    def digits(self, n: int) -> str:
        return "".join(self.rng.choice(string.digits) for _ in range(n))

    def word(self, n: int) -> str:
        """A pronounceable lowercase nonsense word of length n."""
        start = self.rng.random() < 0.5
        return "".join(self.rng.choice(_VOW if (i % 2) == start else _CONS) for i in range(n))

    def scramble(self, orig: str) -> str:
        """Replace every letter and digit, keeping length, case and punctuation."""
        out = []
        for tok in _TOKEN.findall(orig):
            if tok[0].isdigit():
                out.append(self.digits(len(tok)))
            elif tok[0].isalnum():
                w = self.word(len(tok))
                out.append("".join(c.upper() if o.isupper() else c for c, o in zip(w, tok)))
            else:
                out.append("".join(self._layout(c) for c in tok))
        s = "".join(out)
        # Nothing replaceable (pure punctuation): the layout *is* the value.
        return self.word(len(orig)) if s == orig and orig else s

    def _layout(self, c: str) -> str:
        """Keep ASCII punctuation/whitespace; replace any other symbol (emoji, ...)."""
        return c if c in _LAYOUT else self.word(1)

    def extend(self, base: str, n: int) -> str:
        """Append n random characters (used when a generator's domain runs out)."""
        if base[-1:].isdigit():
            return base + self.digits(n)
        tail = self.word(n)
        return base + (tail.upper() if base.isupper() else tail)

    def _fill(self, orig: str, digits: str) -> str:
        """Lay ``digits`` into the digit positions of ``orig``; scramble letters."""
        it = iter(digits)
        out = []
        for c in orig:
            if c.isdigit():
                out.append(next(it))
            elif c.isalpha():
                w = self.word(1)
                out.append(w.upper() if c.isupper() else w)
            else:
                out.append(self._layout(c))
        return "".join(out)

    # -- typed generators ------------------------------------------------
    def name(self, o: str) -> str:
        fn, ln = self.f.first_name(), self.f.last_name()
        return self._case(o, f"{ln}, {fn}" if "," in o else f"{fn} {ln}")

    def email(self, o: str) -> str:
        _, sep, dom = o.rpartition("@")
        if not sep:
            return self.scramble(o)
        key = dom.casefold()
        if key not in self._domains:
            taken = set(self._domains.values())
            while True:
                d = f"{self.word(self.rng.randint(5, 9))}.example"
                if d not in taken:
                    break
            self._domains[key] = d
        user = self.f.user_name()
        if self.rng.random() < 0.5:
            user += str(self.rng.randint(1, 999))
        return self._case(o, f"{user}@{self._domains[key]}")

    def phone(self, o: str) -> str:
        ds = [c for c in o if c.isdigit()]
        n = len(ds)
        if n == 0:
            return self.scramble(o)
        if n == 10 or (n == 11 and ds[0] == "1"):
            # NANP shape: use the 555 exchange, which is not assigned to subscribers.
            new = f"{self.rng.randint(2, 9)}{self.digits(2)}555{self.digits(4)}"
            if n == 11:
                new = "1" + new
        else:
            new = str(self.rng.randint(1, 9)) + self.digits(n - 1)
        return self._fill(o, new)

    def ssn(self, o: str) -> str:
        if sum(c.isdigit() for c in o) != 9:
            return self.scramble(o)
        # Area numbers 000 and 666 are never issued.
        return self._fill(o, self.rng.choice(("000", "666")) + self.digits(6))

    def credit_card(self, o: str) -> str:
        n = sum(c.isdigit() for c in o)
        if n < 12:
            return self.scramble(o)
        body = str(self.rng.randint(1, 9)) + self.digits(n - 2)
        return self._fill(o, body + _luhn(body))

    def ipv4(self, o: str) -> str:
        if not _IPV4.fullmatch(o):
            return self.scramble(o)
        r = self.rng.randint
        return f"10.{r(0, 255)}.{r(0, 255)}.{r(1, 254)}"

    def uuid(self, o: str) -> str:
        u = uuid.UUID(int=self.rng.getrandbits(128), version=4)
        if len(o) != 36:
            return self.hex(o)
        return self._case(o, str(u))

    def hex(self, o: str) -> str:
        out = []
        for c in o:
            if c in string.hexdigits:
                h = self.rng.choice(_HEXCH)
                out.append(h.upper() if c.isupper() else h)
            elif c.isalnum():
                out.append(self.scramble(c))
            else:
                out.append(self._layout(c))
        return "".join(out)

    def url(self, o: str) -> str:
        scheme, sep, rest = o.partition("://")
        if not sep:
            return self.scramble(o)
        if scheme.lower() not in _SCHEMES:
            scheme = "https"
        host = f"{self.word(self.rng.randint(5, 10))}.example"
        path = f"/{self.word(self.rng.randint(4, 10))}" if "/" in rest.rstrip("/") else ""
        return f"{scheme}://{host}{path}"

    def state(self, o: str) -> str:
        pool = _US.states_abbr if len(o.strip()) == 2 else _US.states
        return self._case(o, self.rng.choice(pool))

    def country(self, o: str) -> str:
        n = len(o.strip())
        if n == 2 and o.isalpha():
            return self._case(o, self.f.country_code())
        if n == 3 and o.isalpha():
            return self._case(o, self.f.country_code(representation="alpha-3"))
        return self._case(o, self.f.country())
