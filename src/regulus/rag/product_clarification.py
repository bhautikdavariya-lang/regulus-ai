"""AMB1 (30 Oct, off until measured): a question about a requirement that 21 CFR sets separately for each type of product
- food, drugs, medical devices, cosmetics - that does not say which product it is about gets a clarifying question
listing the parallel provisions, instead of one product's rule chosen for it.

full300d: "How must net quantity of contents be declared?" was answered from 801.62 (devices) and "What must the name and
place of business declaration include?" from 801.1; the key is the food rule (101.7, 101.5). The question supports
neither choice: 101.7, 201.51, 201.62, 701.13 and 801.62 all carry the heading "Declaration of net quantity of contents",
and the picker's top candidates were exactly those sections.

How systems that answer ambiguous questions do it, and what is taken from each:
  * weigh the cost of a wrong guess against the cost of asking: guess and say so when a wrong guess is cheap, ask when
    the stakes are high (OpenAI Model Spec, "state assumptions, and ask clarifying questions when appropriate"). Another
    product's labeling rule given as the answer is a compliance error, so this asks;
  * ground the clarification in the corpus - offer only readings the documents answer, named concretely (retrieval-
    augmented clarification; Tree of Clarifications, EMNLP 2023): the options are the parallel sections retrieval
    itself ranked first, each with its citation and heading;
  * do not let a small model decide whether a question is ambiguous (CLAMBER, ACL 2024: LLMs detect ambiguity poorly and
    prompting makes small ones overconfident): detection here is deterministic - heading identity across product parts;
  * scope selection, as legal research tools take the jurisdiction (Lexis+ AI, CoCounsel): the reply names the product
    type ("food", "for a medical device") and the follow-up is answered from that type's section(s)
    (regulus.rag.conversation, `narrowed`).

Nothing here calls a model; the clarifying answer cites only sections the index holds, under their own headings."""
from __future__ import annotations

import re
from dataclasses import dataclass

# product families of 21 CFR, by part number, in the order they are offered
FAMILIES: tuple[tuple[str, str, tuple[int, int]], ...] = (
    ("food", "Food", (100, 199)),
    ("drug", "Drugs", (200, 499)),
    ("device", "Medical devices", (800, 898)),
    ("cosmetic", "Cosmetics", (700, 799)),
    ("biologic", "Biologics", (600, 680)),
    ("animal_food", "Animal food and drugs", (500, 599)),
    ("tobacco", "Tobacco products", (1100, 1150)),
)
LABELS = {key: label for key, label, _ in FAMILIES}
# a reply choosing a family (and a question naming one: it is not ambiguous)
# (the everyday names of products count: "a triangular cheese package", "It's a shampoo")
_FAMILY_WORDS = {
    "food": r"foods?|beverages?|dietary\s+supplements?|infant\s+formulas?|grocer\w*|snacks?|juices?|cheeses?|cand(?:y|ies)|"
            r"milk|dairy|meats?|poultry|seafood|fish|eggs?|fruits?|vegetables?|produce|bread|cereals?|flour|honey|"
            r"chocolates?|coffee|teas?|spices?|bottled\s+water|soft\s+drinks?|sodas?|baked\s+goods|confectioner\w*|recipes?",
    "drug": r"drugs?|medicines?|medications?|over-the-counter|pharmaceuticals?|tablets?|capsules?|ointments?|"
            r"sunscreens?|antiperspirants?|inhalers?|insulin|antacids?|analgesics?|acetaminophen|ibuprofen|aspirin|naproxen",
    "device": r"(?:medical\s+)?devices?|diagnostics?|implants?|syringes?|catheters?|contact\s+lens(?:es)?|condoms?|"
              r"gloves?|thermometers?|hearing\s+aids?|wheelchairs?|bandages?|test\s+kits?",
    "cosmetic": r"cosmetics?|make-?up|lotions?|shampoos?|conditioners?|lipsticks?|fragrances?|perfumes?|colognes?|"
                r"skin\s*care|soaps?|nail\s+polish|mascaras?|eye\s*shadows?|deodorants?|hair\s+dyes?|hair\s*sprays?|moisturi[sz]ers?",
    "biologic": r"biologics?|biological\s+products?|vaccines?|blood(?:\s+products?)?",
    "animal_food": r"animals?|pets?|feeds?|veterinary|livestock",
    "tobacco": r"tobacco|cigarettes?|e-?cigarettes?|cigars?|vap(?:e|es|ing)",
}
_FAMILY_ACRONYMS = {"drug": r"OTC|Rx", "device": r"IVDs?", "tobacco": r"ENDS"}
_FAMILY_RE = {k: re.compile(r"(?<!\w)(?:" + v + r")(?!\w)", re.I) for k, v in _FAMILY_WORDS.items()}
_ACRONYM_RE = {k: re.compile(r"(?<!\w)(?:" + v + r")(?!\w)") for k, v in _FAMILY_ACRONYMS.items()}
# words that name a product but no family ("color additive" questions belong to Parts 70-82, decided elsewhere)
_OTHER_PRODUCT = re.compile(r"(?<!\w)(?:colou?r\s+additives?|colou?rants?|food\s+additives?|GRAS)(?!\w)", re.I)

# a heading's product prefix ("Drugs; ", "Medical devices; ") and product words ("of package form food")
_PREFIX = re.compile(r"^(?:[a-z ]+);\s*", re.I)
_PRODUCT_PHRASE = re.compile(r"\b(?:package\s+form|packaged\s+form|foods?|drugs?|medical\s+devices?|devices?|cosmetics?)\b", re.I)
_HEADING_STOP = frozenset({"of", "the", "and", "or", "a", "an", "in", "for", "to", "by", "on", "with"})
# sections whose heading says nothing about the subject: never a parallel group of their own
_GENERIC_HEADINGS = ("scope", "purpose", "definitions", "applicability", "general", "reserved", "general requirements",
                     "definitions and interpretations", "purpose and scope", "incorporation by reference")

TOP = 6          # the candidates read for the first-ranked one's parallels
SIMILAR = 0.6    # word overlap (Jaccard) of two headings without their product words
MIN_FAMILIES = 2   # a reply chooses among at least this many offered types
# ... and a question is asked about only when retrieval itself ranked the same provision for this many product types among
# its first TOP candidates (8,088 gold-labelled bank questions: 18 asked about - 15 truly unspecified, the same question
# written from 101.1, 201.60, 701.10 and 801.60 - and 3 naming the product by an everyday word, now in _FAMILY_WORDS). 300Q (full300d candidates): at 4 it fires on L-004 and L-005 only (5 types each); at 3 also
# K-008 ("records from a nonclinical laboratory study" - 117.315 / 507.208 / 1114.45 ranked first, Part 58 named in
# words), at 2 on 12 questions about food vs animal food CGMP (FSVP V-001..V-005) and drug vs device sponsors (P-010)
MIN_RANKED_FAMILIES = 4
MAX_SECTIONS = 6   # a conversation anchor holds six sections (regulus.rag.conversation.Anchor): every one offered is choosable


def family_of(section: str) -> str | None:
    part = section.split(".")[0]
    if not part.isdigit():
        return None
    n = int(part)
    return next((key for key, _, (lo, hi) in FAMILIES if lo <= n <= hi), None)


def names_family(text: str) -> set[str]:
    """The product families the text names."""
    t = text or ""
    return ({k for k, rx in _FAMILY_RE.items() if rx.search(t)} | {k for k, rx in _ACRONYM_RE.items() if rx.search(t)})


def heading_words(heading: str) -> frozenset[str]:
    h = _PREFIX.sub("", (heading or "").strip().rstrip("."))
    h = _PRODUCT_PHRASE.sub(" ", h).lower()
    return frozenset(w for w in re.findall(r"[a-z]+", h) if w not in _HEADING_STOP)


_GENERIC = frozenset(heading_words(h) for h in _GENERIC_HEADINGS)
SUBJECT_WORDS = 2   # heading words the question itself uses (its 5-letter stems): L-004 and L-005 use three


def _question_words(question: str) -> frozenset[str]:
    """The question's words cut to 5 letters, matched against heading words cut the same way ("declared" ~ "declaration")."""
    return frozenset(w[:5] for w in re.findall(r"[a-z]+", (question or "").lower()) if w not in _HEADING_STOP)


def _similar(a: frozenset[str], b: frozenset[str]) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= SIMILAR


@dataclass(frozen=True)
class Choice:
    section: str
    heading: str
    subpart: str = ""


def choices(question: str, cands: list[dict], index) -> dict[str, tuple[Choice, ...]] | None:
    """{family: the parallel sections of that family} when the question names no product type and its first-ranked
    regulation candidates are the same provision written for different product types; None otherwise. `index`: the
    section index (regulus.retrieval.section_index.SectionIndex), for the parallel sections the candidates left out."""
    if names_family(question) or _OTHER_PRODUCT.search(question or ""):
        return None
    cfr = [c for c in cands if not c.get("statute") and family_of(c["section"])][:TOP]
    # only the first-ranked candidate - the question's subject - opens a group: "What must nutrition labeling include?"
    # ranks 101.9 first, and the net-quantity group below it is not what it asks about
    for seed in cfr[:1]:
        words = heading_words(seed.get("heading", ""))
        if len(words) < 2 or words in _GENERIC:
            continue
        if len({w[:5] for w in words} & _question_words(question)) < SUBJECT_WORDS:
            continue   # the question does not ask about what the heading names ("When does the rule apply to most businesses?")
        ranked = [c for c in cfr if _similar(words, heading_words(c.get("heading", "")))]
        if len({family_of(c["section"]) for c in ranked}) < MIN_RANKED_FAMILIES:
            continue
        # the parallels retrieval left out of its first places, from the whole index (101.7's group has five sections)
        found: dict[str, list[Choice]] = {}
        for s, h, sp in zip(index.sections, index.headings, index.subparts):
            fam = family_of(s)
            if fam and _similar(words, heading_words(h)):
                found.setdefault(fam, []).append(Choice(s, (h or "").strip().rstrip("."), sp or ""))
        ordered = [c for k, _, _ in FAMILIES if k in found for c in sorted(found[k], key=_section_order)][:MAX_SECTIONS]
        kept: dict[str, tuple[Choice, ...]] = {}
        for c in ordered:
            kept[family_of(c.section)] = kept.get(family_of(c.section), ()) + (c,)
        if len(kept) >= MIN_FAMILIES:
            return kept
    return None


def _section_order(c: Choice) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", c.section))


def sections(found: dict[str, tuple[Choice, ...]]) -> tuple[str, ...]:
    return tuple(c.section for group in found.values() for c in group)


def _subpart(sp: str) -> str:
    """"subpart c - labeling requirements for over-the-counter drugs" -> "Subpart C: labeling requirements for ..."."""
    m = re.match(r"^\s*subpart\s+([a-z0-9]+)\s*[-\u2014:]\s*(.+)$", sp or "", re.I)
    if m:
        return f"Subpart {m.group(1).upper()}: {m.group(2).strip()}"
    sp = (sp or "").strip()
    return sp[:1].upper() + sp[1:]


def answer(found: dict[str, tuple[Choice, ...]]) -> str:
    """The clarifying answer: the parallel provisions by product type, cited under their own headings."""
    lines = ["The answer depends on the type of product, and the question does not say which. 21 CFR sets this "
             "requirement separately for each type:"]
    for key, group in found.items():
        entries = []
        for c in group:
            where = f", {_subpart(c.subpart)}" if len(group) > 1 and c.subpart else ""
            entries.append(f"21 CFR {c.section} ({c.heading}{where})")
        lines.append(f"- {LABELS[key]}: " + "; ".join(entries))
    examples = " or ".join(f'"{LABELS[k].lower()}"' for k in list(found)[:2])
    lines.append(f"Which type of product is it? Reply with the product type - for example {examples} - and the answer "
                 "will come from that section.")
    return "\n".join(lines)


def suggestions(cfr: list[str]) -> list[str]:
    """The replies a reader can click: one per product type the clarification offered."""
    fams = [k for k, _, _ in FAMILIES if any(family_of(s) == k for s in cfr)]
    return [f"It is for {LABELS[k].lower()}." for k in fams] if len(fams) >= MIN_FAMILIES else []


# a reply that chooses a product type is short: the family words and at most this many words of its own
REPLY_OWN_WORDS = 3
_REPLY_STOP = frozenset("it is its it's for a an the this that these my our we're we are about product products type "
                        "kind one regarding re please thanks thank you yes".split())


def narrowed(reply: str, anchor_cfr: tuple[str, ...]) -> tuple[str, tuple[str, ...]] | None:
    """(family, its sections) when `reply` chooses exactly one of the product types the anchored sections span - the
    answer to a clarification ("food", "It is for a medical device.", "OTC drug") - None otherwise."""
    spanned = {family_of(s) for s in anchor_cfr} - {None}
    if len(spanned) < MIN_FAMILIES:
        return None
    chosen = names_family(reply) & spanned
    if len(chosen) != 1:
        return None
    rest = reply or ""
    for rx in list(_FAMILY_RE.values()) + list(_ACRONYM_RE.values()):
        rest = rx.sub(" ", rest)
    own = [w for w in re.findall(r"[a-z']+", rest.lower()) if w not in _REPLY_STOP and len(w) > 1]
    if len(own) > REPLY_OWN_WORDS:
        return None   # a new question that happens to name a product type: answered on its own
    fam = chosen.pop()
    return fam, tuple(s for s in anchor_cfr if family_of(s) == fam)
