"""Color additives a question names, matched to the listing sections that name them (21 CFR Parts 73, 74 and 82).

Why this exists (23 Oct 2026, section-resolution benchmark): a question naming "FD&C Blue No. 1" was given 74.2340
(FD&C Red No. 40) because the picker matched the question's shape (aluminum lake, eye area) and ignored the name; one
naming "FD&C Yellow No. 6" and "Part 82" was given 82.50 (General). The corpus already knows which section lists which
color: every listing section's heading is the color's name. This index is built from those headings only - no
hand-made list - so it covers every listed color, now and after any listing is added.

  * Certified colors ("FD&C Blue No. 1", "D&C Red No. 6", "Ext. D&C Violet No. 2", "Citrus Red No. 2") are keyed by
    (family, hue, number). A question may write them loosely ("Blue 1", "FD&C Blue #1", "Red No.40", "blue 1 lake");
    a hue and number without a family match every family that lists that number ("Violet 2": D&C and Ext. D&C).
  * Colors exempt from certification are keyed by their heading's name, each ";"-part and parenthesized alias, with
    singular forms of plural names ("Iron oxides." -> "iron oxides", "iron oxide"; "Cochineal extract; carmine." ->
    "cochineal extract", "carmine"). Single words match as whole words only.

Headings that name no color ("General.", "Definitions.", "Lakes (FD&C).", "Certifiable mixtures.", "Diluents in color
additive mixtures ...") are not listings of a color: they are never vetoed or forced by a name.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

LISTING_PARTS = frozenset({"73", "74", "82"})
_HUES = "Red|Blue|Green|Yellow|Orange|Violet|Brown|Black"
_FAMILY = {"fd&c": "fdc", "fdc": "fdc", "fd and c": "fdc", "d&c": "dc", "d and c": "dc", "ext d&c": "extdc",
           "external d&c": "extdc", "citrus": "citrus"}
_HEAD_CERT = re.compile(rf"^(FD&C|D&C|Ext\.\s*D&C|Citrus)\s+({_HUES})\s+No\.\s*(\d+)", re.I)
_Q_CERT = re.compile(rf"(?<![A-Za-z])(?:(FD\s*&\s*C|FD and C|FDC|Ext\.?\s*D\s*&\s*C|External D&C|D\s*&\s*C|D and C|Citrus)\s+)?"
                     rf"({_HUES})\s*(?:No\.?|Number|#)?\s*(\d{{1,2}})(?!\d|\.\d|\s*(?:%|percent|ppm|days?|months?|years?|mg\b|g\b))", re.I)
_NOT_A_COLOR = re.compile(r"^(?:general|definitions?|scope|lakes\b|certifiable|diluents?\b|general specifications|specifications)", re.I)
_LAKE = re.compile(r"\blakes?\b", re.I)


# words that make a question about color: an exempt color's name is often also an ordinary ingredient ("our talc body
# powder may be adulterated", 23 Oct: FD&C Act 611 lost to the talc listing), a certified name never is
_COLOR_CONTEXT = re.compile(r"\b(?:colou?r(?:s|ed|ing|ants?)?|pigments?|tint(?:s|ed|ing)?|shades?|dyes?|lakes?|hues?|"
                            r"pearlescent|shimmer)\b", re.I)


def names_a_color(question: str, match: "ColorMatch") -> bool:
    """A match that names a color additive as a color: a certified name always; an exempt color's name only in a
    question that speaks of color."""
    return any(k[0] == "cert" for k in match.keys) or bool(_COLOR_CONTEXT.search(question or ""))


def normalize_heading(heading: str) -> str:
    """'FD&C Blue No. 1.' and 'FD&C Blue No. 1' (74.1101 has no period) are the same heading."""
    return " ".join((heading or "").split()).rstrip(". ").lower()


def _family(raw: str | None) -> str | None:
    if not raw:
        return None
    return _FAMILY.get(" ".join(re.sub(r"\s*&\s*", "&", raw.lower().replace(".", " ")).split()))


def _aliases(heading: str) -> list[str]:
    """The names an exempt-color heading answers to (lower case)."""
    h = normalize_heading(heading)
    out: list[str] = []
    for part in [p.strip() for p in h.split(";") if p.strip()]:
        inner = re.findall(r"\(([^)]+)\)", part)
        bare = " ".join(re.sub(r"\([^)]*\)", " ", part).split())
        for name in [bare] + [i.strip() for i in inner if re.search(r"[a-z]{3}", i) and not re.search(r"\d", i)]:
            if name and name not in out:
                out.append(name)
            if name.endswith("s") and not name.endswith("ss") and len(name) > 4 and name[:-1] not in out:
                out.append(name[:-1])   # "iron oxides" -> "iron oxide"; "ultramarines" -> "ultramarine"
    return out


@dataclass(frozen=True)
class ColorMatch:
    keys: tuple[tuple, ...]     # ("cert", family, hue, number) / ("name", alias): one mention may name several
    text: str                   # the words of the question that matched
    sections: tuple[str, ...]   # every listing section of the color(s) named (shorter names inside it included)
    lake: bool = False          # the question speaks of a lake of it
    exact: tuple[str, ...] = () # the listings of the name exactly as matched ("astaxanthin dimethyldisuccinate", not
                                # the "astaxanthin" inside it); for a certified name, every family it can mean


@dataclass
class EntityIndex:
    cert: dict[tuple[str, str, str], list[str]] = field(default_factory=dict)       # (family, hue, number) -> sections
    names: dict[str, list[str]] = field(default_factory=dict)                       # alias -> sections
    listing_key: dict[str, tuple] = field(default_factory=dict)                     # section -> its color's key(s)
    _name_re: re.Pattern | None = None

    @classmethod
    def from_sections(cls, sections, parts, headings) -> "EntityIndex":
        ix = cls()
        for s, p, h in zip(sections, parts, headings):
            if p not in LISTING_PARTS or not h or _NOT_A_COLOR.match(h.strip()):
                continue
            m = _HEAD_CERT.match(h.strip())
            if m:
                k = (_family(m.group(1)), m.group(2).lower(), str(int(m.group(3))))
                ix.cert.setdefault(k, []).append(s)
                ix.listing_key[s] = ("cert",) + k
                continue
            al = _aliases(h)
            for a in al:
                ix.names.setdefault(a, []).append(s)
            if al:
                ix.listing_key[s] = ("name", al[0])
        names = sorted(ix.names, key=len, reverse=True)
        ix._name_re = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(n) for n in names) + r")(?![a-z0-9])") if names else None
        return ix

    def is_color_listing(self, section: str) -> bool:
        return section in self.listing_key

    def match(self, question: str) -> list[ColorMatch]:
        """The colors the question names, one match per mention, in order of mention (a color mentioned twice is one
        match). A loose certified name ("Blue 1") counts only when some family lists that hue and number, and names all
        of them ("Violet 2": D&C and Ext. D&C Violet No. 2). Exempt colors match by whole-word alias, longest first; a
        name inside a longer one belongs to that mention ("annatto extract" also names the "Annatto." listings)."""
        q = question or ""
        low = q.lower()
        found: list[tuple[int, int, tuple[tuple, ...], bool]] = []
        for m in _Q_CERT.finditer(q):
            fam, hue, num = _family(m.group(1)), m.group(2).lower(), str(int(m.group(3)))
            keys = tuple(("cert",) + k for k in self.cert if k[1] == hue and k[2] == num and (fam is None or k[0] == fam))
            if keys:
                found.append((m.start(), m.end(), keys, bool(_LAKE.search(q[m.end():m.end() + 24]))))
        if self._name_re is not None:
            for m in self._name_re.finditer(low):
                s, e = m.start(), m.end()
                if any(fs <= s < fe for fs, fe, _, _ in found):
                    continue
                inner = tuple(("name", a) for a in self.names
                              if a != m.group(1) and re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", m.group(1)))
                found.append((s, e, (("name", m.group(1)),) + inner, bool(_LAKE.search(low[e:e + 24]))))
        out: list[ColorMatch] = []
        for s, e, keys, lake in sorted(found):
            prev = next((i for i, o in enumerate(out) if set(o.keys) == set(keys)), None)
            if prev is not None:   # the same color again ("Blue No. 1 and ... Blue No. 1 Aluminum Lake")
                out[prev] = ColorMatch(out[prev].keys, out[prev].text, out[prev].sections, out[prev].lake or lake, out[prev].exact)
                continue
            secs = tuple(dict.fromkeys(x for k in keys for x in (self.cert[k[1:]] if k[0] == "cert" else self.names[k[1]])))
            exact = secs if keys[0][0] == "cert" else tuple(self.names[keys[0][1]])
            out.append(ColorMatch(keys, q[s:e], secs, lake, exact))
        return out

    def color_keys(self, section: str) -> tuple | None:
        return self.listing_key.get(section)

    def is_certified_listing(self, section: str) -> bool:
        """A listing of a certified color: its name (family, hue, number) is precise, so a question naming another
        certified color cannot mean it. Exempt colors' names are not (\"pearlescent mica pigment\", \"krill meal\")."""
        return (self.listing_key.get(section) or ("",))[0] == "cert"


_LOCK = threading.Lock()
_CACHE: dict[int, EntityIndex] = {}


def entity_index(section_ix) -> EntityIndex:
    """One entity index per SectionIndex (built from its headings, no query)."""
    with _LOCK:
        key = id(section_ix)
        if key not in _CACHE:
            _CACHE[key] = EntityIndex.from_sections(section_ix.sections, section_ix.parts, section_ix.headings)
        return _CACHE[key]
