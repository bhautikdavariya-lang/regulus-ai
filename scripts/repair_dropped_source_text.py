"""Restore eCFR section text the original ingestion dropped (EXTRACT block quotes, FP flush paragraphs).

    python scripts/repair_dropped_source_text.py plan     --sources DIR --targets FILE --out PLAN.json
    python scripts/repair_dropped_source_text.py apply    --plan PLAN.json --authorized-sha256 SHA --manifest OUT.json
    python scripts/repair_dropped_source_text.py rollback --manifest OUT.json --authorized-sha256 SHA

`plan` is read-only (regulus.retrieval.db's server-enforced read-only session). DIR holds part-<N>.xml payloads and the
fetch logs (*.json lists of {part, url, retrieved_utc, sha256, verified}); a payload is used only if its SHA-256 equals
the source_payload_sha256 of every stored row of the part. FILE is a JSON list of {"section", "paragraph_path"} anchors.
The plan file records the digest that `apply` must be given: the authorisation is for that exact change, from that
exact source, with that provenance.

`apply` creates the manifest file first (refusing an existing file or a missing directory), recomputes the plan
read-only and refuses unless the authorised digest, the plan file's digest and the recomputed digest are one and the
same, then applies the recomputed plan in one transaction on a separate writable connection (same
REGULUS_DATABASE_URL, never printed). The manifest is written and fsynced inside that transaction, before the commit.
If anything fails, nothing is committed and the manifest file is renamed *.not_applied.json. `rollback` (given the
manifest's digest) undoes an applied manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.ingestion import dropped_text as DT  # noqa: E402
from regulus.retrieval.db import Database, DatabaseConfig  # noqa: E402


def load_targets(path: Path) -> dict[str, dict[str, set[str]]]:
    """{part: {section: {anchor paths}}}."""
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for t in json.loads(path.read_text(encoding="utf-8")):
        out[t["section"].split(".")[0]][t["section"]].add(t["paragraph_path"])
    return out


def load_sources(directory: Path) -> tuple[dict[str, bytes], dict[str, dict]]:
    logs: dict[str, dict] = {}
    for f in sorted(directory.glob("*.json")):
        for rec in json.loads(f.read_text(encoding="utf-8")):
            if rec.get("verified"):
                logs[rec["part"]] = rec
    return {p: (directory / f"part-{p}.xml").read_bytes() for p in logs}, logs


def make_plan(query: Callable, sources: Path, targets_file: Path) -> tuple[list[DT.SectionPlan], dict[str, dict], dict[str, Any]]:
    """(section plans, provenance, plan file content) from a read-only query function."""
    payloads, logs = load_sources(sources)
    targets = load_targets(targets_file)
    plans: list[DT.SectionPlan] = []
    provenance: dict[str, dict] = {}
    for part, secs in sorted(targets.items()):
        if part not in payloads:
            raise DT.RepairError(f"no verified payload for part {part} in {sources}")
        plans += DT.plan_part(query, part, payloads[part], {s: set(p) for s, p in secs.items()})
        provenance[part] = {k: logs[part][k] for k in ("url", "sha256", "retrieved_utc")}
    planned_anchors = {(p.section_number, r.paragraph_path) for p in plans for r in p.inserts}
    idle = [f"{s}{a}" for part in targets.values() for s, anchors in part.items() for a in sorted(anchors)
            if (s, a) not in planned_anchors]
    content = {"plan_sha256": DT.plan_digest(plans, provenance), "provenance": provenance, "sources": str(sources),
               "targets_file": str(targets_file),
               "sections": [{**asdict(p), "inserts": [asdict(r) for r in p.inserts]} for p in plans],
               "summary": {"sections": len(plans), "planned": sum(p.status == "planned" for p in plans),
                           "misaligned": [p.section_number for p in plans if p.status == "misaligned"],
                           "rows_to_insert": sum(len(p.inserts) for p in plans),
                           "ordinals_to_renumber": sum(len(p.ordinal_updates) for p in plans),
                           "targets_with_nothing_to_restore": idle,
                           "untargeted_dropped_in_planned_sections": sum(len(p.untargeted_dropped) for p in plans
                                                                         if p.status == "planned")}}
    return plans, provenance, content


def writable_connection():
    import psycopg
    from psycopg.rows import dict_row
    cfg = DatabaseConfig.from_env()
    conn = psycopg.connect(cfg.url, connect_timeout=cfg.connect_timeout, application_name="regulus-source-repair",
                           options=f"-c statement_timeout={cfg.statement_timeout_ms}", row_factory=dict_row, autocommit=True)
    conn.read_only = False
    return conn


def cmd_apply(plan_path: Path, authorized: str, manifest_path: Path, query_factory: Callable, conn_factory: Callable) -> dict:
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    handle = open(manifest_path, "x", encoding="utf-8")   # before any database work: refuses overwrite / missing dir
    try:
        with query_factory() as query:
            plans, provenance, fresh = make_plan(query, Path(saved["sources"]), Path(saved["targets_file"]))
        if not (authorized == saved["plan_sha256"] == fresh["plan_sha256"]):
            raise DT.RepairError(f"authorised {authorized}, plan file {saved['plan_sha256']}, recomputed {fresh['plan_sha256']}: "
                                 "not one and the same plan")

        def write_manifest(manifest: dict) -> None:
            handle.write(json.dumps({**manifest, "plan_file": str(plan_path)}, indent=1, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())

        conn = conn_factory()
        try:
            manifest = DT.apply_plans(conn, plans, provenance, authorized, write_manifest)
        finally:
            conn.close()
        handle.close()
        return manifest
    except BaseException:
        handle.close()
        manifest_path.rename(manifest_path.with_suffix(".not_applied.json"))
        raise


class _ReadOnly:
    def __enter__(self):
        self.db = Database.from_env()
        self.db.connect()
        return self.db.query

    def __exit__(self, *exc):
        self.db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--targets", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("apply")
    a.add_argument("--plan", type=Path, required=True)
    a.add_argument("--authorized-sha256", required=True)
    a.add_argument("--manifest", type=Path, required=True)
    r = sub.add_parser("rollback")
    r.add_argument("--manifest", type=Path, required=True)
    r.add_argument("--authorized-sha256", required=True)
    args = ap.parse_args()

    if args.cmd == "plan":
        with _ReadOnly() as query:
            _, _, content = make_plan(query, args.sources, args.targets)
        args.out.write_text(json.dumps(content, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"plan_sha256": content["plan_sha256"], **content["summary"]}, indent=1))
        return 1 if content["summary"]["misaligned"] else 0

    if args.cmd == "apply":
        manifest = cmd_apply(args.plan, args.authorized_sha256, args.manifest, _ReadOnly, writable_connection)
        print(json.dumps({"inserted": len(manifest["inserted"]), "ordinal_updates": len(manifest["ordinal_updates"]),
                          "plan_sha256": manifest["plan_sha256"], "manifest": str(args.manifest)}))
        return 0

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.authorized_sha256 != manifest["plan_sha256"]:
        print("rollback needs the manifest's plan digest", file=sys.stderr)
        return 2
    conn = writable_connection()
    try:
        print(json.dumps(DT.rollback(conn, manifest)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
