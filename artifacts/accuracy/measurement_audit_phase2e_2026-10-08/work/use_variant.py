"""Run a script with regulus.accuracy taken from an offline variant copy (production src untouched)."""
import sys, runpy, regulus
vdir = sys.argv[1]
regulus.__path__.insert(0, vdir + "/regulus")
import regulus.accuracy.verdicts as v
assert v.__file__.startswith(vdir), v.__file__
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
