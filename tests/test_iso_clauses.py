"""ISO1 (27 Oct 2026): the ISO 13485 clauses the cited Part 820 text names."""
from types import SimpleNamespace as NS

from regulus.rag.iso_clauses import clause_line, clauses_in

SRC = [NS(index=1, citation="21 CFR 820.35", text="In addition to the requirements of Clause 4.2.5 in ISO 13485 (incorporated by "
          "reference, see § 820.7), Control of Records, the manufacturer must include the following information:"),
       NS(index=2, citation="21 CFR 820.35(a)", text="(a) Records of complaints. In addition to Clause 8.2.2 in ISO 13485, Complaint "
          "Handling, the manufacturer shall maintain records of the review, evaluation, and investigation of all complaints.")]


def test_clause_lists_and_iso_9000_are_read():
    assert [n for n, _ in clauses_in("In addition to the requirements of Clauses 7.5.1, 7.5.8, and 7.5.9 in ISO 13485")] == ["7.5.1", "7.5.8", "7.5.9"]
    assert clauses_in("The definitions in ISO 13485 and in Clause 3 of ISO 9000 apply") == []


def test_the_missing_clauses_are_named_with_their_citations():
    line = clause_line("Complaint records must name the device [2].", SRC)
    assert "Clause 8.2.2 Complaint Handling (21 CFR 820.35(a)) [2]" in line and "Clause 4.2.5 (21 CFR 820.35) [1]" in line
    assert "8.2.2" not in (clause_line("Under Clause 8.2.2 complaint records must name the device [2].", SRC) or "")
    assert clause_line("No Part 820 source is cited here [9].", SRC) is None
