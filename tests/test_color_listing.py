"""Color-additive listing composer (regulus.rag.color_listing)."""
from dataclasses import dataclass

from regulus.rag.color_listing import compose, products, read_scope


@dataclass
class Src:
    index: int
    citation: str
    text: str


@dataclass
class Pkg:
    requirements: tuple
    sources: tuple


EYE_DEF = Src(6, "21 CFR 70.3(s)", "(s) The term area of the eye means the area enclosed with in the circumference of the supra-orbital ridge.")
EXT_DEF = Src(7, "21 CFR 70.3(v)", "(v) The terms externally applied drugs and externally applied cosmetics mean drugs or cosmetics applied only to external parts of the body and not to the lips or any body surface covered by mucous membrane.")
EYE_RULE = Src(8, "21 CFR 70.5(a)", "(a) Color additives for use in the area of the eye. No listing or certification of a color additive shall be considered to authorize the use of any such color additive in any article intended for use in the area of the eye unless such listing or certification of such color additive specifically provides for such use.")


def listing(uses):
    return (Src(1, "21 CFR 74.2203(a)", "(a) Identity and specifications. The color additive FD&C Green No. 3 shall conform in identity and specifications to the requirements of § 74.203(a)(1) and (b)."),
            Src(2, "21 CFR 74.2203(b)", f"(b) Uses and restrictions. {uses}"),
            Src(3, "21 CFR 74.2203(c)", "(c) Labeling. The label of the color additive shall conform to the requirements of § 70.25 of this chapter."),
            Src(4, "21 CFR 74.2203(d)", "(d) Certification. All batches of FD&C Green No. 3 shall be certified in accordance with regulations in part 80 of this chapter."))


REQS = (("r1", "21 CFR 74.2203"), ("r2", "21 CFR 70.3(s)"), ("r3", "21 CFR 70.5(a)"), ("r4", "21 CFR 70.3(v)"))


def test_scopes():
    assert read_scope("(b) Uses and restrictions. X may be safely used for coloring cosmetics generally in amounts consistent with current good manufacturing practice.").generally
    s = read_scope("(b) Uses and restrictions. X may be safely used for coloring externally applied cosmetics in amounts not exceeding 0.01 percent by weight of the finished cosmetic product.")
    assert s.external and s.limit == "0.01 percent" and not s.eye_included
    assert read_scope("(b) Uses and restrictions. Caramel is safe for use in coloring cosmetics generally, including cosmetics applied to the area of the eye, in amounts consistent with good manufacturing practice.").eye_included
    # anything else is not decided here
    assert read_scope("(c) Uses and restrictions. Henna may be safely used for coloring hair only.") is None
    assert read_scope("(c) Uses and restrictions. Silver may be safely used for coloring fingernail polish at a level not to exceed 1 percent.") is None


def test_products_are_merged_and_classified():
    assert products("a cream blush and a matching eye shadow") == [("cream blush", "ext"), ("eye shadow", "eye")]
    assert products("a lipstick and a body lotion") == [("lipstick", "lips"), ("body lotion", "ext")]


def test_generally_listing_without_eye_use_denies_the_eye_product_with_70_5():
    pkg = Pkg(REQS, listing("The color additive FD&C Green No. 3 may be safely used for coloring cosmetics generally in amounts consistent with current good manufacturing practice.") + (EYE_DEF, EXT_DEF, EYE_RULE))
    out = compose(pkg, "Is FD&C Green No. 3 permitted in our cream blush and our eye shadow?")
    lines = out.splitlines()
    assert lines[0] == "Cream blush: permitted." and "Eye shadow: not permitted." in lines
    assert "21 CFR 70.5(a) states:" in out and "[8]" in out and "21 CFR 74.2203(d) states:" in out
    assert out.count("74.2203(b) states") == 1


def test_externally_applied_listing_denies_lip_products_with_70_3_v():
    pkg = Pkg(REQS, listing("D&C Green No. 8 may be safely used for coloring externally applied cosmetics in amounts not exceeding 0.01 percent by weight of the finished cosmetic product.") + (EYE_DEF, EXT_DEF, EYE_RULE))
    out = compose(pkg, "Can we use FD&C Green No. 3 in a lip balm and a body lotion?")
    assert "Lip balm: not permitted." in out and "Body lotion: permitted." in out and "21 CFR 70.3(v) states:" in out
    assert "Use limit: not exceeding 0.01 percent by weight [2]." in out


def test_undecidable_listing_or_unknown_product_returns_none():
    pkg = Pkg(REQS, listing("Henna may be safely used for coloring hair only.") + (EYE_DEF, EXT_DEF, EYE_RULE))
    assert compose(pkg, "Can we use FD&C Green No. 3 in a body lotion?") is None
    pkg = Pkg(REQS, listing("FD&C Green No. 3 may be safely used for coloring cosmetics generally.") + (EYE_DEF, EXT_DEF, EYE_RULE))
    assert compose(pkg, "Can our supplier sell FD&C Green No. 3?") is None
    # a question that does not name the listing's color is not a listing question (a guessed listing)
    pkg = Pkg(REQS, listing("The color additive FD&C Green No. 3 may be safely used for coloring cosmetics generally.") + (EYE_DEF, EXT_DEF, EYE_RULE))
    assert compose(pkg, "How do FDA's definitions treat a brow tint and a lip gloss?") is None


def test_a_listing_that_also_allows_lip_use_is_left_to_the_model():
    # 74.2333-style text: external AND lip use with a limit - "externally applied" alone would wrongly deny the lipstick
    assert read_scope("(b) Uses and restrictions. D&C Red No. 33 may be safely used for coloring externally applied cosmetics and lip cosmetics in amounts not to exceed 3 percent by weight.") is None


def test_lc1_a_listing_answer_gets_its_uncited_paragraphs(monkeypatch):
    from types import SimpleNamespace as NS

    from regulus.rag.color_listing import LC1_LEAD, missing_listing_paragraphs

    src = [NS(citation="21 CFR 73.2125(a)", index=1, text="(a) Identity and specifications. The color additive shall conform to § 73.125."),
           NS(citation="21 CFR 73.2125(b)", index=2, text="(b) Uses and restrictions. It may be used for coloring dentifrices."),
           NS(citation="21 CFR 73.2125(b)(1)", index=3, text="(1) It shall not be used at a level in excess of 0.1 percent."),
           NS(citation="21 CFR 73.2125(c)", index=4, text="(c) Labeling. The label shall conform to the requirements of § 70.25.")]
    pkg = NS(requirements=(("r1", "21 CFR 73.2125"),), sources=src, earlier_question=None,
             question="We want a green toothpaste colored with chlorophyllin. Is that allowed, and at what level?")
    out = missing_listing_paragraphs(pkg, "Yes, at most 0.1 percent [3]. It may color dentifrices [2].")
    assert out.startswith(LC1_LEAD) and "73.2125(a)" in out and "73.2125(c)" in out and "(b)(1)" not in out
    narrow = NS(**{**pkg.__dict__, "question": "What substances may it be combined with?"})
    assert missing_listing_paragraphs(narrow, "Water and glycerin [3].") is None
    followup = NS(**{**pkg.__dict__, "earlier_question": "Is chlorophyllin allowed?"})
    assert missing_listing_paragraphs(followup, "Yes, at most 0.1 percent [3].") is None
