"""Data models for the semantic experiment: manifest, corpus items, index metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from regulus.config import PROJECT_ROOT
from regulus.retrieval.models import CORPORA

SEMANTIC_DIR = PROJECT_ROOT / "data" / "evaluation" / "semantic"
MANIFEST_PATH = SEMANTIC_DIR / "manifest.yaml"
GENERATED_DIR = SEMANTIC_DIR / "generated"
CORPUS_PATH = GENERATED_DIR / "corpus.jsonl"
CORPUS_META_PATH = GENERATED_DIR / "corpus_meta.json"
VECTORS_PATH = GENERATED_DIR / "vectors.npy"
INDEX_META_PATH = GENERATED_DIR / "index_meta.json"


@dataclass(frozen=True)
class SemanticPaths:
    """File layout of one semantic corpus version.

    None / "stage8"  -> the original Stage 8 layout (manifest.yaml + generated/)
    "<name>"          -> data/evaluation/semantic/<name>/manifest.yaml and
                         data/evaluation/semantic/<name>/generated/
    Stage 8 artifacts are never overwritten by another version.
    """

    name: str
    manifest: Path
    generated: Path

    @property
    def corpus(self) -> Path:
        return self.generated / "corpus.jsonl"

    @property
    def corpus_meta(self) -> Path:
        return self.generated / "corpus_meta.json"

    @property
    def vectors(self) -> Path:
        return self.generated / "vectors.npy"

    @property
    def index_meta(self) -> Path:
        return self.generated / "index_meta.json"


def resolve_paths(name: str | None = None) -> SemanticPaths:
    if not name or name == "stage8":
        return SemanticPaths("stage8", MANIFEST_PATH, GENERATED_DIR)
    if not name.replace("_", "").replace("-", "").isalnum():
        raise SemanticConfigError(f"invalid semantic corpus name {name!r}")
    base = SEMANTIC_DIR / name
    return SemanticPaths(name, base / "manifest.yaml", base / "generated")

POOLINGS = ("cls", "mean")


class SemanticConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EmbeddingConfig:
    model_id: str
    revision: str
    dimension: int
    pooling: str = "cls"
    normalize: bool = True
    max_length: int = 512
    query_instruction: str = ""
    batch_size: int = 16

    def __post_init__(self) -> None:
        if not self.model_id or "/" not in self.model_id:
            raise SemanticConfigError("embedding.model_id must be '<org>/<name>'")
        if not self.revision:
            raise SemanticConfigError("embedding.revision must be pinned")
        if self.dimension <= 0:
            raise SemanticConfigError("embedding.dimension must be positive")
        if self.pooling not in POOLINGS:
            raise SemanticConfigError(f"embedding.pooling must be one of {POOLINGS}")
        if self.max_length <= 0 or self.batch_size <= 0:
            raise SemanticConfigError("max_length and batch_size must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        """Stable hash of every setting that changes the produced vectors."""
        payload = json.dumps(
            {k: v for k, v in self.to_dict().items() if k != "batch_size"}, sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SemanticManifest:
    """Stage 8 (version 1) lists sections/dockets one by one with a role.
    Stage 10 (version 2) selects scope (subchapters, parts, sectors) and lists
    the benchmark targets separately; everything else in scope is a distractor."""

    version: int
    embedding: EmbeddingConfig
    ecfr_sections: tuple[dict[str, str], ...]
    guidance_dockets: tuple[dict[str, str], ...]
    guidance_max_chunks_per_document: int
    source_path: Path | None = None
    name: str = "stage8"
    rationale: str = ""
    ecfr_subchapters: tuple[str, ...] = ()
    ecfr_parts: tuple[str, ...] = ()
    guidance_sectors: tuple[str, ...] = ()
    target_sections: tuple[str, ...] = ()
    target_dockets: tuple[str, ...] = ()

    @property
    def is_scope_based(self) -> bool:
        return self.version >= 2

    def sections(self) -> list[str]:
        return [s["section"] for s in self.ecfr_sections]

    def dockets(self) -> list[str]:
        return [d["docket"] for d in self.guidance_dockets]

    def role_of_section(self, section: str) -> str:
        if self.is_scope_based:
            return "target" if section in self.target_sections else "distractor"
        return next((s.get("role", "target") for s in self.ecfr_sections if s["section"] == section), "unknown")

    def role_of_docket(self, docket: str | None) -> str:
        if self.is_scope_based:
            return "target" if docket and docket.upper() in self.target_dockets else "distractor"
        return next((d.get("role", "target") for d in self.guidance_dockets if d["docket"] == docket), "unknown")

    def scope_summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "ecfr_subchapters": list(self.ecfr_subchapters),
            "ecfr_parts": list(self.ecfr_parts),
            "ecfr_sections": self.sections(),
            "guidance_sectors": list(self.guidance_sectors),
            "guidance_dockets": self.dockets(),
            "guidance_max_chunks_per_document": self.guidance_max_chunks_per_document,
            "target_sections": list(self.target_sections),
            "target_dockets": list(self.target_dockets),
        }


def load_manifest(path: str | Path | None = None, *, corpus: str | None = None) -> SemanticManifest:
    if path is None:
        path = resolve_paths(corpus).manifest
    path = Path(path)
    if not path.is_file():
        raise SemanticConfigError(f"manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    version = int(data.get("version", 1))
    if version >= 2:
        return _load_manifest_v2(data, path, version)
    try:
        emb = data["embedding"]
        sel = data["selection"]
        embedding = EmbeddingConfig(
            model_id=str(emb["model_id"]),
            revision=str(emb["revision"]),
            dimension=int(emb["dimension"]),
            pooling=str(emb.get("pooling", "cls")),
            normalize=bool(emb.get("normalize", True)),
            max_length=int(emb.get("max_length", 512)),
            query_instruction=str(emb.get("query_instruction", "") or ""),
            batch_size=int(emb.get("batch_size", 16)),
        )
        sections = tuple({"section": str(s["section"]), "role": str(s.get("role", "target"))} for s in sel["ecfr_sections"])
        dockets = tuple({"docket": str(d["docket"]).upper(), "role": str(d.get("role", "target"))} for d in sel["guidance_dockets"])
        cap = int(sel.get("guidance_max_chunks_per_document", 60))
    except (KeyError, TypeError, ValueError) as exc:
        raise SemanticConfigError(f"malformed manifest {path}: {exc}") from exc
    if not sections and not dockets:
        raise SemanticConfigError("manifest selects nothing")
    if len({s["section"] for s in sections}) != len(sections) or len({d["docket"] for d in dockets}) != len(dockets):
        raise SemanticConfigError("manifest contains duplicate sections or dockets")
    if cap <= 0:
        raise SemanticConfigError("guidance_max_chunks_per_document must be positive")
    return SemanticManifest(version, embedding, sections, dockets, cap, path)


def _embedding_from(emb: dict[str, Any]) -> EmbeddingConfig:
    return EmbeddingConfig(
        model_id=str(emb["model_id"]),
        revision=str(emb["revision"]),
        dimension=int(emb["dimension"]),
        pooling=str(emb.get("pooling", "cls")),
        normalize=bool(emb.get("normalize", True)),
        max_length=int(emb.get("max_length", 512)),
        query_instruction=str(emb.get("query_instruction", "") or ""),
        batch_size=int(emb.get("batch_size", 16)),
    )


def _load_manifest_v2(data: dict[str, Any], path: Path, version: int) -> SemanticManifest:
    try:
        corpus = data.get("corpus", {})
        name = str(corpus.get("name") or path.parent.name)
        embedding = _embedding_from(data["embedding"])
        sel = data["selection"]
        ecfr = sel.get("ecfr", {}) or {}
        guid = sel.get("guidance", {}) or {}
        targets = sel.get("targets", {}) or {}
        subchapters = tuple(str(s).upper() for s in ecfr.get("subchapters", []) or [])
        parts = tuple(str(p) for p in ecfr.get("parts", []) or [])
        sections = tuple({"section": str(s), "role": "scope"} for s in ecfr.get("sections", []) or [])
        sectors = tuple(str(s) for s in guid.get("sectors", []) or [])
        dockets = tuple({"docket": str(d).upper(), "role": "scope"} for d in guid.get("dockets", []) or [])
        cap = int(guid.get("max_chunks_per_document", 12))
        target_sections = tuple(str(s) for s in targets.get("ecfr_sections", []) or [])
        target_dockets = tuple(str(d).upper() for d in targets.get("guidance_dockets", []) or [])
    except (KeyError, TypeError, ValueError) as exc:
        raise SemanticConfigError(f"malformed manifest {path}: {exc}") from exc
    if not (subchapters or parts or sections or sectors or dockets):
        raise SemanticConfigError("manifest selects nothing")
    for label, values in (("subchapters", subchapters), ("parts", parts), ("sectors", sectors), ("target_sections", target_sections), ("target_dockets", target_dockets)):
        if len(set(values)) != len(values):
            raise SemanticConfigError(f"manifest contains duplicate {label}")
    if any(len(s) != 1 or not s.isalpha() for s in subchapters):
        raise SemanticConfigError("subchapters must be single letters")
    if cap <= 0:
        raise SemanticConfigError("max_chunks_per_document must be positive")
    return SemanticManifest(
        version=version, embedding=embedding, ecfr_sections=sections, guidance_dockets=dockets,
        guidance_max_chunks_per_document=cap, source_path=path, name=name, rationale=str(corpus.get("rationale", "")),
        ecfr_subchapters=subchapters, ecfr_parts=parts, guidance_sectors=sectors,
        target_sections=target_sections, target_dockets=target_dockets,
    )


REQUIRED_ITEM_FIELDS = ("id", "corpus", "text", "content_sha256", "role", "metadata")


@dataclass(frozen=True)
class CorpusItem:
    """One embeddable passage with everything needed to rebuild its citation."""

    id: str
    corpus: str
    text: str
    content_sha256: str
    role: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.corpus not in CORPORA:
            raise SemanticConfigError(f"item {self.id!r}: unknown corpus {self.corpus!r}")
        if not self.id or not self.text.strip():
            raise SemanticConfigError(f"item {self.id!r}: id and text are required")
        if self.content_sha256 != text_sha256(self.text):
            raise SemanticConfigError(f"item {self.id!r}: content_sha256 does not match text")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_items(items: list[CorpusItem]) -> dict[str, int]:
    """Integrity gate used by the corpus builder: raises on duplicates, empty
    text, or missing citation identifiers; returns counts for the meta file."""
    seen: set[str] = set()
    for it in items:
        if it.id in seen:
            raise SemanticConfigError(f"duplicate natural key {it.id!r}")
        seen.add(it.id)
        if not it.text.strip():
            raise SemanticConfigError(f"empty text for {it.id!r}")
        m = it.metadata
        if it.corpus == "ecfr":
            for f in ("section_number", "ecfr_permalink", "part_number", "title"):
                if not m.get(f):
                    raise SemanticConfigError(f"{it.id!r}: missing eCFR identifier {f!r}")
        else:
            for f in ("source_url", "title"):
                if not m.get(f):
                    raise SemanticConfigError(f"{it.id!r}: missing guidance identifier {f!r}")
            if m.get("ordinal") is None:
                raise SemanticConfigError(f"{it.id!r}: missing chunk ordinal")
        if it.role not in ("target", "distractor"):
            raise SemanticConfigError(f"{it.id!r}: role must be target or distractor, got {it.role!r}")
    return {
        "items": len(items),
        "ecfr_items": sum(1 for i in items if i.corpus == "ecfr"),
        "guidance_items": sum(1 for i in items if i.corpus == "fda_guidance"),
        "targets": sum(1 for i in items if i.role == "target"),
        "distractors": sum(1 for i in items if i.role == "distractor"),
    }


def load_corpus(path: str | Path | None = None) -> list[CorpusItem]:
    path = Path(path) if path else CORPUS_PATH
    if not path.is_file():
        raise SemanticConfigError(f"semantic corpus not found: {path} (run scripts/build_semantic_corpus.py)")
    items: list[CorpusItem] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SemanticConfigError(f"{path.name} line {n}: invalid JSON ({exc.msg})") from exc
        missing = [f for f in REQUIRED_ITEM_FIELDS if f not in rec]
        if missing:
            raise SemanticConfigError(f"{path.name} line {n}: missing {missing}")
        item = CorpusItem(**{f: rec[f] for f in REQUIRED_ITEM_FIELDS})
        if item.id in seen:
            raise SemanticConfigError(f"{path.name} line {n}: duplicate id {item.id!r}")
        seen.add(item.id)
        items.append(item)
    if not items:
        raise SemanticConfigError("semantic corpus is empty")
    return items


@dataclass(frozen=True)
class IndexMeta:
    model_id: str
    revision: str
    dimension: int
    pooling: str
    normalize: bool
    max_length: int
    query_instruction: str
    embedding_fingerprint: str
    corpus_sha256: str
    corpus_size: int
    embedded_at_utc: str
    code_version: str
    build_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IndexMeta":
        try:
            return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})
        except TypeError as exc:
            raise SemanticConfigError(f"malformed index metadata: {exc}") from exc
