"""Run scripts/accuracy_validate.py unchanged, with the candidates patched in (or not)."""
import runpy, sys
from pathlib import Path
HERE = Path(__file__).parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "scripts"))
mode = sys.argv.pop(1)
sys.argv[0] = str(ROOT / "scripts/accuracy_validate.py")
if mode == "production":
    runpy.run_path(sys.argv[0], run_name="__main__")
else:
    from candidate import patched
    with patched():
        runpy.run_path(sys.argv[0], run_name="__main__")
