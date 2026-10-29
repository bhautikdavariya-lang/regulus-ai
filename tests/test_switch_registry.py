"""The switch registry (src/regulus/rag/switches.yaml, 29 Oct 2026) accounts for every switch the code reads, every switch
the validator_switches docstring names, and DEFAULT exactly. No database, no model."""
import ast
import textwrap

import pytest

from regulus.rag import switch_registry as R
from regulus.rag import validator_switches


@pytest.fixture(scope="module")
def registry():
    return R.load()


@pytest.fixture(scope="module")
def in_code():
    return R.code_switches()


def test_every_switch_read_in_code_is_in_the_registry(registry, in_code):
    missing = {c: sorted(files) for c, files in in_code.items() if c not in registry["switches"]}
    assert not missing, f"add these to src/regulus/rag/switches.yaml: {missing}"


def test_every_documented_switch_is_in_the_registry(registry):
    assert R.documented_switches() - set(registry["switches"]) == set()


def test_in_default_and_status_default_match_DEFAULT_exactly(registry):
    default = set(validator_switches.DEFAULT.split(","))
    assert {c for c, e in registry["switches"].items() if e["in_default"]} == default
    assert {c for c, e in registry["switches"].items() if e["status"] == "default"} == default


def test_every_entry_is_complete(registry):
    for code, e in registry["switches"].items():
        assert R.CODE.match(code), code
        assert all(k in e for k in R.REQUIRED), code
        assert e["status"] in R.STATUSES and e["stage"] in R.STAGES, code
        assert isinstance(e["introduced"]["commit"], str) and isinstance(e["introduced"]["date"], str), code


def test_every_registry_entry_with_code_is_read_somewhere(registry, in_code):
    assert {c for c, e in registry["switches"].items() if e.get("code", True)} - set(in_code) == set()


def test_no_consistency_problems(registry, in_code):
    assert R.problems(registry, in_code) == []


def test_the_switches_proposed_for_deletion_are_rejected_and_off(registry):
    # docs/CLEANUP_PROPOSAL.md
    for code in ("CV1", "NAV1", "NAV2", "RR1", "MS3", "XP1"):
        assert registry["switches"][code]["status"] == "rejected" and not registry["switches"][code]["in_default"]


def test_run_bundles_name_only_registered_switches(registry):
    for run in registry["meta"]["runs"].values():
        assert set(run["extra"]) <= set(registry["switches"])


def test_the_scanner_reads_every_alias_and_wrapper():
    source = textwrap.dedent('''
        from regulus.rag.validator_switches import enabled as precision_fix
        from regulus.rag import validator_switches as VS
        import regulus.rag.validator_switches as V2S
        from regulus.rag.validator_switches import VALIDATOR_PRECISION

        def _wrap(fix):
            from regulus.rag.validator_switches import enabled
            return enabled(fix)

        def f():
            precision_fix("ZA1")
            VS.enabled("ZB1")
            V2S.enabled("ZC1")
            _wrap("ZD1")
            if "ZE1" in VALIDATOR_PRECISION or "ZF1" in VS.VALIDATOR_PRECISION:
                pass
            other("ZG1")          # not a switch read
            precision_fix("lower")  # not a switch code
    ''')
    assert sorted(R._switch_reads(ast.parse(source))) == ["ZA1", "ZB1", "ZC1", "ZD1", "ZE1", "ZF1"]


def test_problems_reports_an_unregistered_switch_and_a_wrong_in_default(registry):
    reg = {"meta": registry["meta"], "switches": dict(registry["switches"])}
    reg["switches"]["A1"] = {**reg["switches"]["A1"], "in_default": False}
    got = R.problems(reg, {**R.code_switches(), "ZZ9": {"regulus/x.py"}})
    assert any(p.startswith("ZZ9: read in code") for p in got)
    assert any(p.startswith("A1: in_default is False") for p in got)
