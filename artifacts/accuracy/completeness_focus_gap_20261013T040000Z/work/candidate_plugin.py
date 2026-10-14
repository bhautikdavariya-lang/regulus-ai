"""pytest plugin: run the whole session with the candidates patched in (no src/ edits)."""
import sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
_ctx = None


def pytest_configure(config):
    global _ctx
    from candidate import patched
    _ctx = patched()
    _ctx.__enter__()


def pytest_unconfigure(config):
    if _ctx is not None:
        _ctx.__exit__(None, None, None)
