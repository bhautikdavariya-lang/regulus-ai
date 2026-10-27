"""RC1 (27 Oct 2026): the MoCRA small-business exemption decided by rule from FD&C Act 612's text."""
from types import SimpleNamespace as NS

from regulus.rag.mocra_rules import compose

A = NS(citation="FD&C Act § 612(a) [21 U.S.C. 364h(a)]", index=1, text="(a) Responsible persons ... whose average gross annual "
       "sales ... is less than $1,000,000 ... shall be considered small businesses and not subject to the requirements of "
       "section 364b or 364c of this title.")
B = NS(citation="FD&C Act § 612(b) [21 U.S.C. 364h(b)]", index=2, text="(b) The exemptions under subsection (a) shall not apply to "
       "any responsible person or facility engaged in the manufacturing or processing of any of the following products:")
B1 = NS(citation="FD&C Act § 612(b)(1) [21 U.S.C. 364h(b)(1)]", index=3, text="(1) Cosmetic products that regularly come into "
        "contact with mucus membrane of the eye under conditions of use that are customary or usual.")
PKG = NS(sources=[A, B, B1])


def test_an_eye_product_maker_is_not_exempt():
    out = compose(PKG, "We have under $1 million in sales but fill mascara. Do we get the small-business exemption?")
    assert out.startswith("Not exempt as a small business: a maker of mascara products is excluded by FD&C Act § 612(b)(1) [3].")


def test_the_exemption_does_not_reach_adverse_event_reporting():
    out = compose(PKG, "Small businesses under $1 million are exempt from MoCRA adverse event reporting, right?")
    assert out.startswith("The small-business exemption of FD&C Act § 612(a) covers only the requirements of sections 364b and 364c [1].")


def test_without_612_supplied_or_a_small_business_nothing_is_composed():
    assert compose(NS(sources=[B1]), "We are a small brand. Must we register?") is None
    assert compose(PKG, "Must we register our facility?") is None
