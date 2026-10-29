"""The switch registry (switches.yaml beside this module) and its consistency checks (29 Oct 2026).

regulus.rag.validator_switches is where a switch is turned on; switches.yaml is where it is accounted for: purpose,
date, status (experimental / candidate / default / rejected), whether it is in DEFAULT, and the evidence. `problems()`
lists every disagreement between the registry, the code that reads the switches, the validator_switches docstring and
DEFAULT - tests/test_switch_registry.py requires it to be empty, scripts/switch_report.py --check prints it.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).with_name("switches.yaml")
SRC_ROOT = Path(__file__).resolve().parents[2]   # src/
STATUSES = ("default", "candidate", "experimental", "rejected")
STAGES = ("retrieval", "selection", "router", "composer", "generation", "answer_checks", "post_answer", "conversation",
          "planning")
REQUIRED = ("purpose", "stage", "status", "in_default", "introduced", "evidence")
CODE = re.compile(r"^[A-Z][A-Z0-9]{1,4}$")
# a switch named in the validator_switches docstring: "A1", "SP2F", "E1S", "FU2B" - never a question id ("S-018"), a
# constant ("MS1_MAX") or a programme step ("step E3")
_DOC_CODE = re.compile(r"(?<![\w-])(?<!step )([A-Z]{1,3}[0-9]{1,2}[A-Z]?)(?![\w])")
_MODULE = "validator_switches"


def load(path: Path = REGISTRY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def default_switches() -> frozenset[str]:
    from regulus.rag import validator_switches

    return frozenset(x.strip() for x in validator_switches.DEFAULT.split(",") if x.strip())


def documented_switches() -> frozenset[str]:
    """Every switch code the validator_switches docstring names."""
    from regulus.rag import validator_switches

    return frozenset(_DOC_CODE.findall(validator_switches.__doc__ or ""))


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _switch_reads(tree: ast.AST) -> list[str]:
    """The switch codes one module reads: enabled("X") under any alias or through a one-line wrapper (conversation._fu2),
    validator_switches.enabled("X") under any module alias, and "X" in VALIDATOR_PRECISION."""
    accessors, modules = {"enabled"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                if node.module.endswith(_MODULE) and a.name == "enabled":
                    accessors.add(a.asname or a.name)
                elif a.name == _MODULE:
                    modules.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.endswith(_MODULE):
                    modules.add(a.asname or a.name)

    def is_read(call: ast.Call) -> bool:
        f = call.func
        if isinstance(f, ast.Name):
            return f.id in accessors
        return isinstance(f, ast.Attribute) and f.attr == "enabled" and (
            _dotted(f.value) in modules or _dotted(f.value).endswith(_MODULE))

    for node in ast.walk(tree):   # wrappers: def f(fix): ... return enabled(fix)
        if isinstance(node, ast.FunctionDef) and node.args.args:
            param = node.args.args[0].arg
            for r in ast.walk(node):
                if (isinstance(r, ast.Return) and isinstance(r.value, ast.Call) and is_read(r.value) and r.value.args
                        and isinstance(r.value.args[0], ast.Name) and r.value.args[0].id == param):
                    accessors.add(node.name)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and is_read(node):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and CODE.match(arg.value):
                out.append(arg.value)
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            if any(isinstance(o, (ast.In, ast.NotIn)) for o in node.ops) and any(
                    _dotted(c).split(".")[-1] == "VALIDATOR_PRECISION" for c in node.comparators):
                if CODE.match(node.left.value):
                    out.append(node.left.value)
    return out


def code_switches(*roots: Path) -> dict[str, set[str]]:
    """switch code -> the files (relative to their root) that read it, over every .py file under `roots`
    (default: src/regulus and scripts/)."""
    roots = roots or (SRC_ROOT / "regulus", SRC_ROOT.parent / "scripts")
    found: dict[str, set[str]] = defaultdict(set)
    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for code in _switch_reads(tree):
                found[code].add(str(path.relative_to(root.parent)))
    return dict(found)


def problems(registry: dict | None = None, in_code: dict[str, set[str]] | None = None) -> list[str]:
    """Every disagreement between the registry and the code, the docstring and DEFAULT; [] when consistent."""
    registry = registry if registry is not None else load()
    in_code = in_code if in_code is not None else code_switches()
    switches = registry.get("switches") or {}
    default = default_switches()
    out = []
    for code in sorted(set(in_code) - set(switches)):
        out.append(f"{code}: read in code ({', '.join(sorted(in_code[code]))}) but not in the registry")
    for code in sorted(documented_switches() - set(switches)):
        out.append(f"{code}: documented in validator_switches but not in the registry")
    for code in sorted(default - set(switches)):
        out.append(f"{code}: in DEFAULT but not in the registry")
    for code, e in sorted(switches.items()):
        e = e or {}
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            out.append(f"{code}: missing {', '.join(missing)}")
        if e.get("status") not in STATUSES:
            out.append(f"{code}: status {e.get('status')!r} is not one of {', '.join(STATUSES)}")
        if e.get("stage") not in STAGES:
            out.append(f"{code}: stage {e.get('stage')!r} is not one of {', '.join(STAGES)}")
        if bool(e.get("in_default")) != (code in default):
            out.append(f"{code}: in_default is {e.get('in_default')} but DEFAULT {'has' if code in default else 'lacks'} it")
        if (e.get("status") == "default") != (code in default):
            out.append(f"{code}: status {e.get('status')} disagrees with DEFAULT ({'in' if code in default else 'not in'})")
        has_code = e.get("code", True)
        if has_code and code not in in_code:
            out.append(f"{code}: no code reads it (set `code: false` if it was removed or never built)")
        if not has_code and code in in_code:
            out.append(f"{code}: marked `code: false` but read in {', '.join(sorted(in_code[code]))}")
    for run, spec in ((registry.get("meta") or {}).get("runs") or {}).items():
        for code in spec.get("extra") or ():
            if code not in switches:
                out.append(f"run {run}: {code} is not in the registry")
    return out
