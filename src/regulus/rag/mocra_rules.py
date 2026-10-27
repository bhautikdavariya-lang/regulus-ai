"""The MoCRA small-business exemption decided by rule (RC1, 27 Oct 2026; rules as code).

FD&C Act 612 (21 U.S.C. 364h): (a) responsible persons and facilities with average gross annual U.S. cosmetic sales
under $1,000,000 for the previous three years, who do not make the products in (b), are small businesses and "not
subject to the requirements of section 364b or 364c" - 606 (good manufacturing practice) and 607 (registration and
product listing); (b) the exemption never applies to makers of products that (1) contact the mucous membrane of the
eye, (2) are injected, (3) are for internal use, or (4) alter appearance for more than 24 hours. The 4B model reversed
this on bank questions (exempted a mascara maker; extended the exemption to adverse event reporting). The verdict is
read from the question's facts - which product, which duty - and every statement after it is 612's text, verbatim and
cited. A question naming no product of (b) and no duty is answered with (a) and (b) as the conditions, without a
verdict. Fires only when 612's text was supplied and the question is about a small business.
"""
from __future__ import annotations

import re

_SMALL = re.compile(r"\bsmall\s+(?:business|company|companies|brand|firm|maker|manufacturer)s?\b|\$\s?1\s?(?:million|m)\b|"
                    r"\$\s?1,000,000\b|\bunder\s+\$|\b(?:annual|yearly)\s+(?:gross\s+)?(?:sales|revenue)\b", re.I)
# 612(b): the products that take a business out of the exemption, by the words customers use for them
_EXCLUDED = (
    ("(b)(1)", re.compile(r"\b(?:mascaras?|eye\s?liners?|eye\s?shadows?|eyeshadows?|lash\w*|eyelash\w*|brow\w*|eye\s+(?:drops?|makeup|pencils?)|"
                          r"eye[- ]area)\b", re.I)),
    ("(b)(2)", re.compile(r"\binject\w*\b", re.I)),
    ("(b)(3)", re.compile(r"\binternal\s+use\b|\bingest\w*\b|\bswallow\w*\b", re.I)),
    ("(b)(4)", re.compile(r"\bsemi-?permanent\b|\bpermanent\s+(?:hair\s+)?(?:dye|color|tint)s?\b|\btattoo\w*\b|"
                          r"\blasts?\s+(?:for\s+)?(?:more\s+than|over|longer\s+than|beyond)\s+24\b", re.I)),
)
# duties 612(a) covers (364b = 606, 364c = 607) and duties it does not
_COVERED = re.compile(r"\bregist\w*|\blisting\b|\bproduct\s+list\w*|\bgood\s+manufacturing|\bGMP\b|\bmanufacturing\s+practice", re.I)
_NOT_COVERED = re.compile(r"\badverse\s+event|\bsafety\s+substantiation|\bsubstantiat\w*|\blabel\w*|\brecall\w*|\brecords?\b", re.I)


def compose(package, question: str) -> str | None:
    from regulus.rag.generation import _verbatim, whole_sentences

    q = question or ""
    if not _SMALL.search(q):
        return None
    own = [s for s in package.sources if (s.citation or "").startswith("FD&C Act § 612")]
    by_path = {}
    for s in own:
        m = re.match(r"^FD&C Act § 612(\([^ ]+?\))?(?:\s|$)", s.citation or "")
        if m:
            by_path[m.group(1) or ""] = s
    a, b = by_path.get("(a)"), by_path.get("(b)")
    if a is None or b is None:
        return None
    hits = [(path, pat.search(q).group(0)) for path, pat in _EXCLUDED if pat.search(q)]
    lines: list[str] = []
    quote = lambda s: f"{s.citation} (verbatim): {_verbatim(whole_sentences(s.text or ''), s.index)}"
    if hits:
        path, word = hits[0]
        src = by_path.get(path) or b   # the clauses of (b) may come as one block
        lines.append(f"Not exempt as a small business: a maker of {word} products is excluded by FD&C Act § 612{path} [{src.index}].")
    elif _NOT_COVERED.search(q) and not _COVERED.search(q):
        lines.append(f"The small-business exemption of FD&C Act § 612(a) covers only the requirements of sections 364b and 364c [{a.index}].")
    elif _COVERED.search(q):
        lines.append(f"Exempt if the conditions of FD&C Act § 612(a) are met and no product of § 612(b) is made [{a.index}].")
    lines += [quote(a), quote(b)] + [quote(by_path[p]) for p in ("(b)(1)", "(b)(2)", "(b)(3)", "(b)(4)") if p in by_path]
    return "\n".join(lines)
