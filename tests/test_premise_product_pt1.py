from regulus.rag.claim_validation import covered_product_words

MICA_B = ("(b) Uses and restrictions. Mica is safe for use in coloring cosmetics generally, including cosmetics applied to "
          "the area of the eye, in amounts consistent with good manufacturing practice.")


def test_pt1_eye_shadow_is_covered_by_an_express_eye_area_use():
    assert {"shadow"} <= covered_product_words("Is mica permitted as a color additive in eye shadow?", [MICA_B])


def test_pt1_eye_use_needs_an_express_statement_not_cosmetics_generally():
    text = "(b) Uses and restrictions. The color additive may be safely used in coloring cosmetics generally."
    assert covered_product_words("Can we use it in an eye shadow?", [text]) == set()


def test_pt1_an_exception_is_not_a_permission():
    text = "(c) It may be used in cosmetics generally, except that it may not be used in the area of the eye."
    assert covered_product_words("Is it permitted in mascara?", [text]) == set()


def test_pt1_external_products_are_covered_by_cosmetics_generally():
    assert "lotion" in covered_product_words("Can it color a body lotion?", [MICA_B])
