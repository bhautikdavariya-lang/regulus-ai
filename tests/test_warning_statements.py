"""WC1 (27 Oct 2026): a Part 740 warning asked for is quoted verbatim with its section."""
from types import SimpleNamespace as NS

from regulus.rag.warning_statements import compose

SRC = [NS(citation="21 CFR 740.11(a)", index=1, text="(a)(1) The label of a cosmetic in a self-pressurized container shall bear:"),
       NS(citation="21 CFR 740.11(a)(1)", index=2, text="Warning—Avoid spraying in eyes. Contents under pressure."),
       NS(citation="21 CFR 740.11(a)(2)", index=3, text="(2) In the case of products intended for use by children, the phrase may be added.")]
PKG = NS(requirements=(("r1", "21 CFR 740.11"),), sources=SRC)


def test_the_warning_and_its_section_are_quoted():
    out = compose(PKG, "We're launching an aerosol dry shampoo. What warning must the can carry?")
    assert out.startswith("The label must bear the statement in 21 CFR 740.11(a)(1) [2]")
    assert "Avoid spraying in eyes. Contents under pressure [2]." in out and "740.11(a)(2)" in out


def test_whether_questions_are_left_to_the_model():
    assert compose(PKG, "Our hairspray uses a hydrocarbon propellant. Do we need the warning, and are there exemptions?") is None
    assert compose(PKG, "Is our pump spray covered by 740.11?") is None
