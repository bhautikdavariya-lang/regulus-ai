"""Color-additive listing answers composed from the listing's own text (22 Oct 2026).

A question about using a listed color additive in a cosmetic ("Is D&C Red No. 6 permitted in our lipstick and our
eyeliner, and does it need certification?") is answered by four facts the regulations state outright: the listing's
uses-and-restrictions paragraph (cosmetics generally / externally applied cosmetics / including the area of the eye /
a percentage limit), FDA's definitions of the area of the eye (21 CFR 70.3(s)) and of externally applied cosmetics
(70.3(v)), the rule that a listing authorizes eye-area use only if it says so (70.5(a)), and the listing's own
identity, labeling and certification paragraphs. Qwen3-4B-Instruct-2507 states these well in about half of such
questions and in the rest adds a restriction the listing does not contain or drops a paragraph (cosmetics benchmark,
22 Oct: "invents a restriction excluding the area of the eye"); a rule cannot.

The composer decides only what those texts decide: each product named in the question is placed by a fixed list of
product words (eye area, lips or mucous membrane, other external use), and each listing's uses paragraph is read for
the phrases above. Anything else - an unrecognized product, a uses paragraph with any other restriction ("only",
"except", "not more than ... ppm" etc. beyond the handled patterns), a listing without the expected paragraphs - and
the composer returns None: the model answers as before. Every statement quotes the provision it rests on, with that
source's number, and the result goes through the same validator as a model answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from regulus.rag.validator_switches import enabled as precision_fix

LISTING_RE = re.compile(r"^21 CFR (7[34]\.2\d{3}a?|82\.\d{3,4}a?)$")
GENERAL_82 = {"82.3", "82.5", "82.6", "82.50", "82.51", "82.1050", "82.1051", "82.2050", "82.2051"}

# product words -> where the product is used. Eye area: 21 CFR 720.4(c)(3) eye makeup preparations and 70.3(s);
# lips / mucous membrane: 70.3(v); everything else listed here is applied to external parts of the body.
EYE = r"eye ?liners?|eyeliners?|eye ?shadows?|eyeshadows?|mascaras?|eyebrow(?: pencils?| tints?| gels?)?|brow (?:tints?|pencils?|gels?|powders?)|eye (?:pencils?|creams?|lotions?|makeup(?: removers?)?|gels?|serums?)|lash (?:serums?|tints?)"
LIPS = r"lip ?sticks?|lipsticks?|lip (?:balms?|gloss(?:es)?|liners?|scrubs?|tints?|stains?|products?|colou?rs?|masks?|plumpers?|oils?)|toothpastes?|mouthwash(?:es)?|dentifrices?|breath (?:fresheners?|sprays?)|lozenges?"
EXTERNAL = (r"(?:body |hand |foot |face |facial |night |day |tinted )?(?:lotions?|creams?|butters?|moisturi[sz]ers?|serums?)|body washe?s?|"
            r"shower gels?|shampoos?|conditioners?|soaps?|nail (?:polish(?:es)?|lacquers?|enamels?|colou?rs?)|blush(?:es)?|"
            r"(?:face |pressed |loose )?powders?|foundations?|concealers?|bronzers?|highlighters?|(?:body |face |sugar |salt )?scrubs?|"
            r"bath (?:oils?|bombs?|salts?|gels?)|bubble baths?|perfumes?|colognes?|deodorants?|antiperspirants?|"
            r"sunscreens?|body (?:paints?|oils?|glitters?|sprays?)|hair (?:gels?|sprays?|pomades?|masks?)|face masks?|cleansers?|toners?|"
            r"aftershaves?|shaving creams?|body butters?")
_PRODUCT_RE = re.compile(rf"\b(?P<eye>{EYE})\b|\b(?P<lips>{LIPS})\b|\b(?P<ext>{EXTERNAL})\b", re.I)

# UR1 (27 Oct): the uses paragraph's heading as the listings write it - "Uses and restrictions." (209 paragraphs),
# "Use and restrictions." (5: carmine 73.2087 ...) and "Use and restriction." (annatto 73.2030); the exact form missed 6
_USES_HEADING_UR1 = r"^\([a-z]\)\s*Uses?\s+and\s+restrictions?\."
_GENERALLY = re.compile(r"\bcosmetics generally\b", re.I)
_EXTERNAL = re.compile(r"\bexternally applied (?:drugs and )?cosmetics\b|\bexternally applied drugs and cosmetics\b", re.I)
_EYE_IN = re.compile(r"\bincluding\b[^.;]{0,60}?\barea of the eye\b", re.I)
_LIMIT = re.compile(r"\b(?:in amounts )?not (?:exceeding|to exceed) (?P<amt>[\d.]+ percent)\b", re.I)
_GMP = re.compile(r"\bconsistent with (?:current )?good manufacturing practice\b", re.I)
# any other qualifying language means the paragraph says more than the composer can decide
_OTHER = re.compile(r"\b(?:only|except|excluding|exclusive|shall not|may not|limited to|provided that|subject to|unless|"
                    r"hair dyes?|ingested|surgical sutures|injection|mouthwash|dentifrice|lips?|lipsticks?|nail|tattoo)\b", re.I)


@dataclass(frozen=True)
class Scope:
    generally: bool
    external: bool
    eye_included: bool
    limit: str | None


def _strip(text: str) -> str:
    return re.sub(r"^\([a-z0-9]+\)\s*(?:[A-Z][A-Za-z ,]+\.\s+)?", "", (text or "").strip())


def read_scope(uses_text: str) -> Scope | None:
    """The uses-and-restrictions paragraph as a Scope, or None when it says anything else."""
    body = _strip(uses_text)
    residue = _EYE_IN.sub(" ", _LIMIT.sub(" ", _GMP.sub(" ", body)))
    if _OTHER.search(residue):
        return None
    generally, external = bool(_GENERALLY.search(body)), bool(_EXTERNAL.search(body))
    if generally == external:      # neither (some other use) or both (ambiguous): not decided here
        return None
    m = _LIMIT.search(body)
    return Scope(generally, external, bool(_EYE_IN.search(body)), m.group("amt") if m else None)


def products(question: str) -> list[tuple[str, str]]:
    """(product as written, 'eye' | 'lips' | 'ext') in question order, first mention only. Product words written next
    to each other are one product ("cream blush", "lip balm stick"); its use is the most restricted of its words."""
    rank = {"eye": 0, "lips": 1, "ext": 2}
    merged: list[list] = []   # [start, end, name, kind]
    for m in _PRODUCT_RE.finditer(question or ""):
        kind = next(k for k in ("eye", "lips", "ext") if m.group(k))
        if merged and question[merged[-1][1]:m.start()].strip() == "":
            last = merged[-1]
            last[1], last[2] = m.end(), question[last[0]:m.end()]
            last[3] = min(last[3], kind, key=rank.get)
            continue
        merged.append([m.start(), m.end(), m.group(0), kind])
    out, seen = [], set()
    for _, _, name, kind in merged:
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append((name, kind))
    return out


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+(?=[A-Z(§])", _strip(text)) if s]


_EYE_RULE = ("No listing or certification of a color additive shall be considered to authorize the use of any such color "
             "additive in any article intended for use in the area of the eye unless such listing or certification of such "
             "color additive specifically provides for such use.")


def _quote(source) -> str:
    return f"{source.citation} states: \"{_strip(source.text)}\" [{source.index}]"


def _names_listing(question: str, package, label: str) -> bool:
    """True when the question names the listing's color: every word of the listing's identity (its heading, from the
    first source's "Heading" field when present, otherwise the identity sentence) other than "No." and digits must be
    in the question, and so must its color-index number."""
    src = next((s for s in package.sources if (s.citation or "").startswith(label)), None)
    heading = (getattr(src, "heading", None) or "").strip().rstrip(".")
    if not heading:
        m = re.search(r"The color additive ([^,]+?) shall conform", (src.text if src else "") or "")
        heading = m.group(1) if m else ""
    if not heading:
        return False
    q = " ".join((question or "").lower().split())
    words = [w for w in re.findall(r"[a-z&]+|\d+[a-z]?", heading.lower()) if w not in ("no", "the")]
    # plural headings ("Ultramarines.", "Iron oxides.") match the singular in the question
    stems = [w[:-1] if len(w) > 4 and w.endswith("s") and not w.isdigit() else w for w in words]
    return bool(stems) and all(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?:e?s)?(?![a-z0-9])", q) for w in stems)


def compose(package, question: str) -> str | None:
    """The answer for a package whose requested provisions are color-additive listings, or None.

    Each verdict is one short line ("Lipstick: not permitted.") followed by the quoted provisions that decide it; every
    other paragraph of the requested provisions is quoted with its source number, so the answer is complete and each
    statement is the regulation's own wording."""
    by_label: dict[str, list] = {}
    for s in package.sources:
        sec = re.match(r"^(21 CFR \d+\.\d+[a-z]?)", s.citation or "")
        if sec:
            by_label.setdefault(sec.group(1), []).append(s)
    listings = [label for _, label in package.requirements if LISTING_RE.match(label) and label[7:] not in GENERAL_82]
    if not listings or len(listings) > 2:
        return None
    named = products(question)
    if not named:
        return None

    def uses_of(label):
        rows = by_label.get(label, [])
        if label.startswith("21 CFR 82."):
            cand = [s for s in rows if _GENERALLY.search(s.text or "") or _EXTERNAL.search(s.text or "")]
        else:
            cand = [s for s in rows if re.match(_USES_HEADING_UR1 if precision_fix("UR1") else r"^\([a-z]\)\s*Uses and restrictions\.",
                                                 (s.text or "").strip())]
        return cand[0] if len(cand) == 1 else None

    primary = next((label for label in listings if uses_of(label) is not None), None)
    if primary is None:
        return None
    # the question must name the color the listing is for ("FD&C Green No. 3", "caramel", "D&C Red No. 6"): a
    # definitions question with a guessed listing is not a listing question (code review: 70.3-Q3). In a follow-up
    # ("Can we use it in an eye shadow?") the conversation named it: the earlier question counts; the products judged
    # are still the follow-up's own (regulus.rag.conversation)
    named_in = question + (" " + package.earlier_question if getattr(package, "earlier_question", None) else "")
    if not _names_listing(named_in, package, primary):
        return None
    uses = uses_of(primary)
    scope = read_scope(uses.text)
    if scope is None:
        return None
    use_sentence = next((x for x in _sentences(uses.text) if _GENERALLY.search(x) or _EXTERNAL.search(x)), None)
    if use_sentence is None:
        return None
    eye_rule = [s for s in by_label.get("21 CFR 70.5", []) if (s.citation or "").startswith("21 CFR 70.5(a)")]
    defs = {s.citation: s for s in by_label.get("21 CFR 70.3", [])}
    eye_def, ext_def = defs.get("21 CFR 70.3(s)"), defs.get("21 CFR 70.3(v)")
    use_quote = f"{uses.citation} states: \"{use_sentence}\" [{uses.index}]"
    lines: list[str] = []
    groups: dict[str, list[str]] = {}
    for product, kind in named:
        verdict = ("eye_no" if kind == "eye" and not scope.eye_included else
                   "lips_no" if kind == "lips" and scope.external else "yes")
        groups.setdefault(verdict, []).append(product)
    for verdict, names in groups.items():
        who = " and ".join(names)
        who = who[0].upper() + who[1:]
        if verdict == "eye_no":
            if not (eye_rule and eye_def):
                return None
            lines += [f"{who}: not permitted.", _quote(eye_def) + ".", use_quote + ".",
                      f"21 CFR 70.5(a) states: \"{_EYE_RULE}\" [{eye_rule[0].index}]."]
        elif verdict == "lips_no":
            if ext_def is None:
                return None
            lines += [f"{who}: not permitted.", use_quote + ".", _quote(ext_def) + "."]
        else:
            lines += [f"{who}: permitted.", use_quote + "."]
    seen_lines: set[str] = set()
    lines = [ln for ln in lines if not (ln in seen_lines or seen_lines.add(ln))]   # each quotation once
    if scope.limit:
        lines.append(f"Use limit: not exceeding {scope.limit} by weight [{uses.index}].")
    elif _GMP.search(use_sentence):
        lines.append(f"Use limit: no percentage is stated; the amount is consistent with good manufacturing practice [{uses.index}].")
    quoted = {uses.index}
    for label in listings:
        for s in by_label.get(label, []):
            if s.index not in quoted:
                lines.append(_quote(s) + ".")
                quoted.add(s.index)
    cited = {int(m) for m in re.findall(r"\[(\d+)\]", "\n".join(lines))}
    requested = {label for _, label in package.requirements}
    for s in package.sources:
        sec = re.match(r"^(21 CFR \d+\.\d+[a-z]?)", s.citation or "")
        if s.index in cited or sec is None:
            continue
        if sec.group(1) in requested or s.citation in requested:
            lines.append(_quote(s) + ".")
    return "\n".join(re.sub(r"\.\.$", ".", ln) for ln in lines)


# Fix C82 (23 Oct 2026, regulus.rag.validator_switches): a Part 82 certification listing that is a single conformity
# sentence ("The color additive D&C Red No. 28 shall conform in identity and specifications to the requirements of
# § 74.1328 (a)(1) and (b)"), with at most the lakes sentence ("All lakes of ... shall be manufactured from previously
# certified batches"). The model restated these correctly but did not say that the section itself sets no use
# restriction or amount limit, or turned the subpart's "may be certified ... if" into a mandate (82.1328, 82.1330,
# 82.705 on the 22 Oct holdout). Composed only when the question is about Part 82, certification or specifications and
# names the color, and when the subpart's general section is supplied; anything else and the model answers as before.
_CONFORM = re.compile(r"^(?:\([a-z]\)\s*)?The color additive (?P<name>.+?) shall conform in identity and specifications to the "
                      r"requirements of §\s*(?P<ref>74\.\d+[a-z]?)\s*\(a\)\s*\(1\) and \(b\) of this chapter\.$")
_LAKES = re.compile(r"^(?:\([a-z]\)\s*)?All lakes\b.{0,90}? shall be manufactured from previously certified batches of the "
                    r"straight color additive\.$")   # 82.706(b): "All lakes including current D&C external and D&C lakes of ..."
_ASKS_CERTIFICATION = re.compile(r"\bpart 82\b|\b82\.\d{2,4}|\bcertif|\bspecification", re.I)
# subpart B (FD&C) sections are 82.50-82.706, subpart C (D&C) 82.1050-82.1710, subpart D (Ext. D&C) 82.2050-82.2707a
_SUBPART_GENERAL = {"1": "21 CFR 82.1050", "2": "21 CFR 82.2050"}


def compose_certification(package, question: str) -> str | None:
    """The answer for a question about a Part 82 conformity-only listing, or None (see _CONFORM above)."""
    if not _ASKS_CERTIFICATION.search(question or ""):
        return None
    listings = [label for _, label in package.requirements if LISTING_RE.match(label) and label.startswith("21 CFR 82.")
                and label[7:] not in GENERAL_82]
    if len(listings) != 1:
        return None
    label = listings[0]
    own = [s for s in package.sources if re.match(rf"^{re.escape(label)}(?:\(|$)", s.citation or "")]
    conform = [s for s in own if _CONFORM.match(" ".join((s.text or "").split()))]
    others = [s for s in own if s not in conform]
    if len(conform) != 1 or not all(_LAKES.match(" ".join((s.text or "").split())) for s in others):
        return None
    if not _names_listing(question, package, label):
        return None
    section = label[7:]
    number = re.match(r"82\.(\d+)", section).group(1)
    general_label = _SUBPART_GENERAL.get(number[0], "21 CFR 82.50") if len(number) == 4 else "21 CFR 82.50"
    general = next((s for s in package.sources if s.citation == general_label), None)
    if general is None:
        return None
    c = conform[0]
    m = _CONFORM.match(" ".join(c.text.split()))
    conformity = (f"{m.group('name')} shall conform in identity and specifications to the requirements of "
                  f"21 CFR {m.group('ref')}(a)(1) and (b) [{c.index}].")
    lines = [f"{label} contains one requirement: {conformity}" if not others else f"{c.citation}: {conformity}"]
    lines += [_quote(s) + "." for s in others]
    # a scoped absence the validator checks against the cited text (A2 "use" kind); an amount absence is not claimed,
    # because only a uses paragraph can show that no amount limit exists
    lines.append(f"{label} states no use restriction [{c.index}].")
    lines.append(_quote(general) + ".")
    # 82.5, when supplied (an FD&C certification question): which of its limits govern this color, then every
    # paragraph quoted with its own citation (the subpart C/D limits stay, labelled by their own text)
    spec = [s for s in package.sources if s.citation == "21 CFR 82.5" or (s.citation or "").startswith("21 CFR 82.5(")]
    own_limits = [s for s in spec if (s.citation or "").startswith("21 CFR 82.5(b)(1)")]
    if spec and own_limits and general_label == "21 CFR 82.50":
        lines.append(f"{m.group('name')} is a straight color listed in subpart B, so the subpart B limits in 21 CFR "
                     f"82.5(b)(1) apply to it {''.join(f'[{s.index}]' for s in own_limits)}.")
    lines += [_quote(s) + "." for s in spec]
    return "\n".join(re.sub(r"\.\.$", ".", ln) for ln in lines)
