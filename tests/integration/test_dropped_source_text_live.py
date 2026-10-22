"""Live, read-only: the eCFR text the original ingestion dropped after the anchor rows in
artifacts/retrieval_repair_step1_20261021/targets.json is stored. The anchors are those the retrieval root-cause report
flagged (71.1(c) excluded, 701.13(i)(4) added so every repaired section is complete). Fails while the text is missing;
passes once scripts/repair_dropped_source_text.py has applied the authorised plan. Uses the hash-verified part payloads
in artifacts/retrieval_repair_step1_20261021/source_xml. Skipped when the database or the payloads are unavailable.
Step 2 (22 Oct 2026, artifacts/retrieval_repair_step2_20261022) is checked the same way: every dropped EXTRACT, FP and
table of the twelve cosmetic parts except the blank form templates (71.1(c), 80.21(j)(1)-(4))."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from regulus.config import PROJECT_ROOT
from regulus.ingestion import dropped_text as DT

pytestmark = pytest.mark.integration

STEPS = [PROJECT_ROOT / "artifacts" / "retrieval_repair_step1_20261021", PROJECT_ROOT / "artifacts" / "retrieval_repair_step2_20261022"]


@pytest.fixture(scope="module", params=STEPS, ids=lambda s: s.name)
def step(request):
    if not (request.param / "targets.json").exists() or not (request.param / "source_xml").exists():
        pytest.skip("source payloads or targets not present")
    return request.param


@pytest.fixture(scope="module")
def db():
    from regulus.retrieval.db import Database
    try:
        database = Database.from_env()
        database.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unavailable: {type(exc).__name__}")
    yield database
    database.close()


@pytest.fixture(scope="module")
def plans(db, step):
    targets: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for t in json.loads((step / "targets.json").read_text(encoding="utf-8")):
        targets[t["section"].split(".")[0]][t["section"]].add(t["paragraph_path"])
    out = []
    for part, secs in targets.items():
        out += DT.plan_part(db.query, part, (step / "source_xml" / f"part-{part}.xml").read_bytes(), {s: set(p) for s, p in secs.items()})
    return out


def test_every_targeted_section_aligns_with_its_verified_source(plans):
    assert [p.section_number for p in plans if p.status == "misaligned"] == []


def test_no_dropped_text_remains_after_the_flagged_anchors(plans):
    missing = [f"{p.section_number}{r.paragraph_path}#{r.path_ordinal} <{r.source_tag}> {r.body_text[:60]}" for p in plans for r in p.inserts]
    assert missing == []


def test_restored_rows_carry_the_anchor_provenance_and_their_own_content_hash(db, step):
    rows = db.query("""
        SELECT r.section_number, r.paragraph_path, r.path_ordinal, r.body_text, r.content_sha256, r.source_payload_sha256,
               r.source_endpoint, r.snapshot_date, a.source_payload_sha256 AS a_sha, a.source_endpoint AS a_url,
               a.snapshot_date AS a_date, r.ordinal, a.ordinal AS a_ordinal
        FROM cfr_records r JOIN cfr_records a ON a.section_number = r.section_number AND a.paragraph_path = r.paragraph_path
             AND a.path_ordinal = 0 AND a.removed_on IS NULL
        WHERE r.section_number = ANY(%(s)s) AND r.path_ordinal > 0 AND r.removed_on IS NULL""",
                    {"s": sorted({t["section"] for t in json.loads((step / "targets.json").read_text(encoding="utf-8"))})})
    assert rows, "no restored rows"
    for r in rows:
        assert r["content_sha256"] == DT.content_hash(r["body_text"])
        assert (r["source_payload_sha256"], r["source_endpoint"], r["snapshot_date"]) == (r["a_sha"], r["a_url"], r["a_date"])
        assert r["ordinal"] > r["a_ordinal"]


def test_section_ordinals_stay_unique_and_contiguous(db, step):
    sections = sorted({t["section"] for t in json.loads((step / "targets.json").read_text(encoding="utf-8"))})
    for s in sections:
        ords = [r["ordinal"] for r in db.query("SELECT ordinal FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL "
                                               "ORDER BY ordinal", {"s": s})]
        assert ords == list(range(ords[0], ords[0] + len(ords))), s
