"""Run a script with regulus.accuracy taken from an EXISTING Phase 2F offline variant copy (read-only use)."""
import os, sys, runpy, regulus
vdir = os.path.abspath(sys.argv[1])
regulus.__path__.insert(0, vdir + "/regulus")
import regulus.accuracy.operators as o
assert o.__file__.startswith(vdir), o.__file__
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
