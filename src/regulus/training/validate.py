"""Dataset quality validation and statistics.

Structural, leakage, secret and negative-behaviour checks need no database.
Provenance, citation and negative-identifier checks are re-verified against
the read-only database when one is available (they are marked "skipped"
otherwise; the pipeline itself only ever emits rows it read from the
database, so an offline run still validates everything it can).
"""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlsplit

from regulus.retrieval.query import parse_cfr_reference
from regulus.training.config import ABSTENTION_CATEGORIES, CATEGORIES, STAGE6_CATEGORIES, TrainingConfig
from regulus.training.models import ExampleError, SOURCE_TYPES, SPLITS, TrainingExample, iter_jsonl
from regulus.training.negatives import is_refusal
from regulus.training.text import normalise_question

# a citation marker "[n]" is not preceded by a letter or digit (chemical formulas such as C[10]H[14]N[2] are text)
_MARK_RE = re.compile(r"(?<![A-Za-z0-9])\[(\d{1,2})\]")
_PART_CITATION_RE = re.compile(r"^21 CFR Part (\d{1,4})(?:, Subpart ([A-Z0-9\-]+))?$")
SECRET_PATTERNS = {
    "database_url": re.compile(r"postgres(?:ql)?://", re.IGNORECASE),
    "password_assignment": re.compile(r"password\s*[:=]\s*\S", re.IGNORECASE),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    "private_key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "api_key_assignment": re.compile(r"api[_-]?key\s*[:=]\s*\S", re.IGNORECASE),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    "hf_token": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
}


@dataclass
class ValidationReport:
    files: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        if len(self.errors) < 200:
            self.errors.append(msg)
        self.checks["error_count"] = self.checks.get("error_count", 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "files": self.files, "checks": self.checks, "errors": self.errors, "stats": self.stats}


# ------------------------------------------------------------------ loading


def load_split_files(paths: dict[str, Path], report: ValidationReport) -> dict[str, list[TrainingExample]]:
    out: dict[str, list[TrainingExample]] = {}
    seen: dict[str, str] = {}
    for split, path in paths.items():
        examples: list[TrainingExample] = []
        if not path.is_file():
            report.error(f"missing file for split {split}: {path.name}")
            out[split] = examples
            continue
        report.files[split] = path.name
        try:
            for line_no, record in iter_jsonl(path):
                try:
                    ex = TrainingExample.from_dict(record)
                except ExampleError as exc:
                    report.error(f"{path.name} line {line_no}: {exc}")
                    continue
                if ex.split != split:
                    report.error(f"{path.name} line {line_no}: split field {ex.split!r} does not match file")
                if ex.id in seen:
                    report.error(f"{path.name} line {line_no}: duplicate id {ex.id} (also in {seen[ex.id]})")
                seen[ex.id] = path.name
                examples.append(ex)
        except ExampleError as exc:
            report.error(str(exc))
        out[split] = examples
    return out


# --------------------------------------------------------------- structural


def check_structure(examples: list[TrainingExample], config: TrainingConfig, report: ValidationReport) -> None:
    n_bad = 0
    for ex in examples:
        problems = []
        if ex.category not in CATEGORIES:
            problems.append(f"unknown category {ex.category!r}")
        if (ex.type == "abstention") != (not ex.grounded):
            problems.append("type/grounded mismatch")
        if ex.category in ABSTENTION_CATEGORIES and ex.type != "abstention":
            problems.append(f"category {ex.category} must have abstention type")
        if ex.category == "citation_grounding":
            supporting = ex.extra.get("supporting_source")
            distractors = set(ex.extra.get("distractors") or [])
            cited_keys = {c.source_key for c in ex.context if c.citation in set(ex.citations)}
            if supporting and supporting not in cited_keys:
                problems.append("citation_grounding must cite its supporting source")
            if cited_keys & distractors:
                problems.append("citation_grounding cites a distractor")
        for c in ex.context:
            if c.source_type not in SOURCE_TYPES:
                problems.append(f"unknown source_type {c.source_type!r}")
        ctx_cites = {c.citation for c in ex.context}
        if ex.grounded:
            if not ex.context or not ex.citations:
                problems.append("grounded example without context/citations")
            missing = [c for c in ex.citations if c not in ctx_cites]
            if missing:
                problems.append(f"citation not among context citations: {missing[0]!r}")
        else:
            if ex.citations:
                problems.append("abstention example must not carry citations")
            if not is_refusal(ex.answer):
                problems.append("abstention answer does not refuse")
        marks = {int(m) for m in _MARK_RE.findall(ex.answer)}
        if any(m < 1 or m > len(ex.context) for m in marks):
            problems.append("answer cites a source index outside the context")
        total = sum(len(c.text) for c in ex.context)
        if total > config.quality.max_context_chars + 200:
            problems.append(f"context too long ({total} chars)")
        if len(ex.question) < 10 or len(ex.answer) < 20:
            problems.append("question or answer too short")
        if problems:
            n_bad += 1
            report.error(f"{ex.id}: " + "; ".join(problems))
    report.checks["structural_invalid"] = n_bad


# ------------------------------------------------------------------ leakage


def check_leakage(by_split: dict[str, list[TrainingExample]], report: ValidationReport) -> None:
    train_q = {normalise_question(e.question) for e in by_split.get("train", [])}
    train_qa = {(normalise_question(e.question), normalise_question(e.answer)) for e in by_split.get("train", [])}
    groups: dict[str, set[str]] = defaultdict(set)
    for split, exs in by_split.items():
        for e in exs:
            groups[e.group].add(split)
    leaks_q = leaks_qa = 0
    for split in ("validation", "test"):
        for e in by_split.get(split, []):
            if normalise_question(e.question) in train_q:
                leaks_q += 1
            if (normalise_question(e.question), normalise_question(e.answer)) in train_qa:
                leaks_qa += 1
    overlap = sorted(g for g, s in groups.items() if len(s) > 1)
    report.checks["leakage_question_exact"] = leaks_q
    report.checks["leakage_question_answer_exact"] = leaks_qa
    report.checks["leakage_group_overlap"] = len(overlap)
    if leaks_qa:
        report.error(f"{leaks_qa} validation/test example(s) duplicate a training example")
    if overlap:
        report.error(f"{len(overlap)} source group(s) span several splits, e.g. {overlap[0]}")


# ------------------------------------------------------------------ secrets


def scan_secrets(paths: dict[str, Path], report: ValidationReport) -> None:
    findings: Counter[str] = Counter()
    env_password = None
    url = os.environ.get("REGULUS_DATABASE_URL", "")
    if url:
        try:
            env_password = urlsplit(url).password
        except ValueError:
            env_password = None
    for split, path in paths.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for name, rx in SECRET_PATTERNS.items():
            n = len(rx.findall(text))
            if n:
                findings[name] += n
        if env_password and len(env_password) >= 4 and env_password in text:
            findings["database_password"] += 1
        if url and url in text:
            findings["database_url_literal"] += 1
    report.checks["secret_findings"] = dict(findings)
    for name, n in findings.items():
        report.error(f"secret scan: {n} match(es) for {name}")


# -------------------------------------------------------------- statistics


def compute_stats(examples: list[TrainingExample]) -> dict[str, Any]:
    by_cat = Counter(e.category for e in examples)
    by_type = Counter(e.type for e in examples)
    by_split = Counter(e.split or "unassigned" for e in examples)
    by_source = Counter()
    ecfr_sections: set[str] = set()
    ecfr_citations: set[str] = set()
    guidance_docs: set[str] = set()
    for e in examples:
        kinds = {c.source_type for c in e.context}
        if not kinds:
            by_source["none"] += 1
        for k in sorted(kinds):
            by_source[k] += 1
        for c in e.context:
            if c.source_type in ("ecfr", "ecfr_hierarchy"):
                ecfr_citations.add(c.citation)
                if c.section:
                    ecfr_sections.add(c.section)
            elif c.source_type == "fda_guidance" and c.url:
                guidance_docs.add(c.url)
    ctx_chars = [sum(len(c.text) for c in e.context) for e in examples]
    return {
        "total": len(examples),
        "by_category": dict(sorted(by_cat.items())),
        "by_type": dict(sorted(by_type.items())),
        "by_split": {s: by_split.get(s, 0) for s in SPLITS},
        "examples_by_source_type": dict(sorted(by_source.items())),
        "ecfr_examples": sum(1 for e in examples if any(c.source_type in ("ecfr", "ecfr_hierarchy") for c in e.context)),
        "guidance_examples": sum(1 for e in examples if any(c.source_type == "fda_guidance" for c in e.context)),
        "negative_examples": by_type.get("abstention", 0),
        "avg_question_chars": round(mean(len(e.question) for e in examples), 1) if examples else 0,
        "avg_answer_chars": round(mean(len(e.answer) for e in examples), 1) if examples else 0,
        "avg_context_chars": round(mean(ctx_chars), 1) if examples else 0,
        "avg_context_items": round(mean(len(e.context) for e in examples), 2) if examples else 0,
        "unique_cfr_citations": len(ecfr_citations),
        "unique_cfr_sections": len(ecfr_sections),
        "unique_guidance_documents": len(guidance_docs),
    }


# ------------------------------------------------------- database checks


def _parse_hierarchy_key(key: str) -> tuple[str, str, str | None]:
    """'ecfr_hierarchy:part:820:subpart:A' -> ('part', '820', 'A'); 'ecfr_hierarchy:section:820.10' -> ('section', '820.10', None)."""
    parts = key.split(":")
    if len(parts) >= 3 and parts[1] == "section":
        return "section", parts[2], None
    if len(parts) >= 5 and parts[1] == "part" and parts[3] == "subpart":
        return "subpart", parts[2], parts[4]
    return "unknown", key, None


def check_against_database(examples: list[TrainingExample], db, report: ValidationReport) -> None:
    """Every context row and citation must exist; every negative identifier must not."""
    sections_needed: set[str] = set()
    guidance_urls: set[str] = set()
    parts_needed: set[str] = set()
    for e in examples:
        for c in e.context:
            if c.source_type == "ecfr":
                sections_needed.add(c.source_key.split(":")[1])
            elif c.source_type == "fda_guidance":
                guidance_urls.add(c.url or "")
            else:
                kind, a, _ = _parse_hierarchy_key(c.source_key)
                (sections_needed if kind == "section" else parts_needed).add(a)
        for cit in e.citations:
            m = _PART_CITATION_RE.match(cit)
            if m:
                parts_needed.add(m.group(1))
            elif cit.startswith("21 CFR "):
                ref = parse_cfr_reference(cit)
                if ref and ref.section:
                    sections_needed.add(ref.section)
        neg = e.extra.get("negative") or {}
        if neg.get("kind") == "paragraph":
            sections_needed.add(neg["section"])

    records: set[tuple[str, str, int]] = set()
    section_paragraphs: set[tuple[str, str]] = set()
    for chunk in _chunks(sorted(sections_needed), 500):
        for r in db.query("SELECT section_number, paragraph_path, path_ordinal FROM cfr_records WHERE removed_on IS NULL AND section_number = ANY(%(s)s)", {"s": chunk}):
            records.add((r["section_number"], r["paragraph_path"] or "", int(r["path_ordinal"] or 0)))
            section_paragraphs.add((r["section_number"], r["paragraph_path"] or ""))
    live_sections = {s for s, _, _ in records}
    section_rows = {r["number"] for chunk in _chunks(sorted(sections_needed), 500) for r in db.query("SELECT number FROM cfr_sections WHERE number = ANY(%(s)s)", {"s": chunk})}
    all_parts = {r["number"] for r in db.query("SELECT number FROM cfr_parts")}
    subparts = {(r["part_number"], r["designation"]) for r in db.query("SELECT part_number, designation FROM cfr_subparts")}
    chunks: set[tuple[str, int]] = set()
    dockets_by_url: dict[str, str | None] = {}
    for chunk in _chunks(sorted(u for u in guidance_urls if u), 200):
        for r in db.query("SELECT g.source_url, g.docket_number, c.ordinal FROM fda_guidance_chunks c JOIN fda_guidance g ON g.id = c.guidance_id WHERE g.source_url = ANY(%(u)s)", {"u": chunk}):
            chunks.add((r["source_url"], int(r["ordinal"])))
            dockets_by_url[r["source_url"]] = r["docket_number"]
    all_dockets = {r["docket_number"].upper() for r in db.query("SELECT docket_number FROM fda_guidance WHERE docket_number IS NOT NULL")}
    reserved: set[int] = set()
    for n in all_parts:
        if "-" in n:
            a, b = n.split("-", 1)
            if a.isdigit() and b.isdigit():
                reserved.update(range(int(a), int(b) + 1))

    invalid_sources = invalid_citations = negative_failures = 0
    for e in examples:
        problems = []
        for c in e.context:
            if c.source_type == "ecfr":
                _, sec, para, po = c.source_key.split(":", 3)
                if (sec, para, int(po)) not in records:
                    problems.append(f"eCFR row not found: {c.source_key}")
            elif c.source_type == "fda_guidance":
                _, rest = c.source_key.split(":", 1)
                url, _, ordinal = rest.rpartition("#")
                if (url, int(ordinal)) not in chunks:
                    problems.append(f"guidance chunk not found: {c.source_key}")
                elif c.docket_number and dockets_by_url.get(url) != c.docket_number:
                    problems.append(f"docket mismatch for {url}")
            else:
                kind, a, b = _parse_hierarchy_key(c.source_key)
                if kind == "section" and a not in section_rows:
                    problems.append(f"section not found: {a}")
                elif kind == "subpart" and (a not in all_parts or (a, b) not in subparts):
                    problems.append(f"subpart not found: {a} {b}")
                elif kind == "unknown":
                    problems.append(f"unparseable hierarchy key {c.source_key}")
        if problems:
            invalid_sources += 1
        cit_problems = []
        for cit in e.citations:
            m = _PART_CITATION_RE.match(cit)
            if m:
                if m.group(1) not in all_parts or (m.group(2) and (m.group(1), m.group(2)) not in subparts):
                    cit_problems.append(cit)
                continue
            if cit.startswith("FDA Guidance"):
                if not any(c.source_type == "fda_guidance" and c.citation == cit and c.url in dockets_by_url for c in e.context):
                    cit_problems.append(cit)
                continue
            ref = parse_cfr_reference(cit)
            if not ref or not ref.section:
                cit_problems.append(cit)
            elif ref.paragraph_path:
                if (ref.section, ref.paragraph_path) not in section_paragraphs:
                    cit_problems.append(cit)
            elif ref.section not in live_sections and ref.section not in section_rows:
                cit_problems.append(cit)
        if cit_problems:
            invalid_citations += 1
            problems.append(f"citation not in database: {cit_problems[0]!r}")
        neg = e.extra.get("negative") or {}
        if neg:
            kind, ident = neg.get("kind"), str(neg.get("identifier", ""))
            bad = False
            if kind == "section":
                bad = ident in section_rows or ident in live_sections
            elif kind == "part":
                bad = ident in all_parts or (ident.isdigit() and int(ident) in reserved)
            elif kind == "docket":
                bad = ident.upper() in all_dockets
            elif kind == "paragraph":
                bad = (neg.get("section"), neg.get("paragraph")) in section_paragraphs or any(s == neg.get("section") and p.startswith(str(neg.get("paragraph"))) for s, p in section_paragraphs)
            if bad:
                negative_failures += 1
                problems.append(f"negative identifier exists in the database: {ident}")
        if problems:
            report.error(f"{e.id}: " + "; ".join(problems))
    report.checks["provenance"] = "verified"
    report.checks["invalid_source_count"] = invalid_sources
    report.checks["invalid_citation_count"] = invalid_citations
    report.checks["negative_validation_failures"] = negative_failures


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ------------------------------------------------- Stage 13 grounding checks


def check_grounding_examples(examples: list[TrainingExample], db, report: ValidationReport) -> None:
    """Stage 13 categories carry claims that must hold against the database:
    a 'wrong context' example is only meaningful if the requested identifier
    really exists, and a mismatch example is only meaningful if the provided
    source really is a different source."""
    from regulus.grounding.identifiers import DatabaseIdentifierIndex, extract_identifier, verify_identifier

    index = DatabaseIdentifierIndex(db)
    counts: Counter[str] = Counter()
    failures = 0
    for ex in examples:
        problems: list[str] = []
        cat = ex.category
        if cat not in ("context_mismatch", "wrong_context", "partial_context", "guidance_mismatch", "citation_grounding"):
            continue
        counts[cat] += 1
        provided = {c.source_key for c in ex.context}
        declared = ex.extra.get("provided_source")
        if declared and declared not in provided:
            problems.append("declared provided_source is not in the context")

        if cat == "context_mismatch":
            neg = ex.extra.get("negative") or {}
            v = verify_identifier(extract_identifier(ex.question), index)
            if v is None or not v.verified_absent:
                problems.append(f"context_mismatch identifier {neg.get('identifier')!r} is not verified absent")
            if not ex.context:
                problems.append("context_mismatch must supply a legitimate source")
        elif cat in ("wrong_context", "partial_context"):
            requested = ex.extra.get("requested_identifier", "")
            v = verify_identifier(extract_identifier(requested), index)
            if v is None or not v.exists:
                problems.append(f"requested identifier {requested!r} must exist in the database")
            ref = parse_cfr_reference(requested)
            for c in ex.context:
                if ref and c.section == ref.section and (cat == "wrong_context" or c.paragraph == ref.paragraph_path):
                    problems.append(f"provided context {c.citation!r} is the requested source, not a mismatch")
        elif cat == "guidance_mismatch":
            sub = ex.extra.get("subtype")
            kinds = {c.source_type for c in ex.context}
            if sub == "regulation_asked_guidance_given" and kinds != {"fda_guidance"}:
                problems.append("expected only guidance context")
            if sub == "guidance_asked_regulation_given" and kinds != {"ecfr"}:
                problems.append("expected only eCFR context")

        if problems:
            failures += 1
            report.error(f"{ex.id} [{cat}]: " + "; ".join(problems))
    report.checks["grounding_example_counts"] = dict(sorted(counts.items()))
    report.checks["grounding_validation_failures"] = failures


def check_stage6_examples(examples: list[TrainingExample], db, report: ValidationReport) -> None:
    """Stage 6 categories carry two claims that must hold against the database.

    Positive: every provision the answer quotes is a live record (already
    covered by check_against_database through the citations).
    Negative: the identifier a partial_provision example reports as absent must
    really be absent, and its section must really exist. That is re-verified
    here from the database, independently of whatever the generator believed.
    """
    stage6 = [e for e in examples if e.category in STAGE6_CATEGORIES]
    report.checks["stage6_examples"] = len(stage6)
    if not stage6:
        return
    partial = [e for e in stage6 if e.category == "partial_provision"]
    wanted: set[tuple[str, str]] = set()
    for e in partial:
        meta = (e.extra or {}).get("missing_provision") or {}
        if meta.get("section") is not None and meta.get("parent_paragraph") is not None and meta.get("requested_child_number") is not None:
            wanted.add((str(meta["section"]), f"{meta['parent_paragraph']}({meta['requested_child_number']})"))
    present: set[tuple[str, str]] = set()
    live_sections: set[str] = set()
    for chunk in _chunks(sorted({sec for sec, _ in wanted}), 500):
        for r in db.query("SELECT section_number, COALESCE(paragraph_path, '') AS p FROM cfr_records WHERE removed_on IS NULL AND section_number = ANY(%(s)s)", {"s": chunk}):
            present.add((r["section_number"], r["p"]))
            live_sections.add(r["section_number"])

    failures = 0
    required = ("requested_identifier", "section", "parent_paragraph", "requested_child_number", "absent_verified", "snapshot_date")
    for e in stage6:
        problems: list[str] = []
        extra = e.extra or {}
        if extra.get("family") != "extractive_grounded":
            problems.append("missing family=extractive_grounded")
        if extra.get("prompt_format") != "grounded":
            problems.append("missing prompt_format=grounded")
        if e.category == "partial_provision":
            meta = extra.get("missing_provision") or {}
            missing_keys = [k for k in required if meta.get(k) is None]
            if missing_keys:
                problems.append(f"missing_provision metadata lacks {missing_keys}")
            else:
                key = (str(meta["section"]), f"{meta['parent_paragraph']}({meta['requested_child_number']})")
                if key in present:
                    problems.append(f"{meta['requested_identifier']} IS present in the snapshot: it cannot be used as an absent identifier")
                if key[0] not in live_sections:
                    problems.append(f"section {key[0]} has no live records; the example is not about a missing child of a real section")
                if meta.get("absent_verified") is not True:
                    problems.append("absent_verified is not True")
                if str(meta["requested_identifier"]) not in e.answer:
                    problems.append("answer does not name the absent identifier")
                elif "not found in the available eCFR data" not in e.answer:
                    problems.append("answer does not state that the identifier was not found")
        else:
            blocks = [ln for ln in e.answer.splitlines() if ln.strip()]
            if len(blocks) != len(e.citations):
                problems.append(f"{len(blocks)} answer block(s) for {len(e.citations)} citation(s)")
        if problems:
            failures += 1
            report.error(f"{e.id} [{e.category}]: " + "; ".join(problems))
    report.checks["stage6_absent_identifiers_checked"] = len(wanted)
    report.checks["stage6_validation_failures"] = failures


# -------------------------------------------------------------- entry point


def validate_dataset(paths: dict[str, Path], config: TrainingConfig, db=None) -> ValidationReport:
    report = ValidationReport()
    by_split = load_split_files(paths, report)
    examples = [e for s in SPLITS for e in by_split.get(s, [])]
    if not examples:
        report.error("no examples loaded")
        return report
    check_structure(examples, config, report)
    check_leakage(by_split, report)
    scan_secrets(paths, report)
    report.checks["duplicate_count"] = len(examples) - len({e.id for e in examples})
    exact = Counter((normalise_question(e.question), normalise_question(e.answer)) for e in examples)
    report.checks["duplicate_question_answer_pairs"] = sum(n - 1 for n in exact.values() if n > 1)
    if report.checks["duplicate_question_answer_pairs"]:
        report.error(f"{report.checks['duplicate_question_answer_pairs']} duplicate question/answer pair(s)")
    if db is not None:
        check_against_database(examples, db, report)
        check_grounding_examples(examples, db, report)
        check_stage6_examples(examples, db, report)
    else:
        report.checks["provenance"] = "skipped (no database)"
        report.checks["invalid_source_count"] = None
        report.checks["invalid_citation_count"] = None
        report.checks["negative_validation_failures"] = None
    report.stats = compute_stats(examples)
    return report
