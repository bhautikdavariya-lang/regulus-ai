"""Run a script with regulus.accuracy taken from an offline variant copy (production src untouched)."""
import sys, runpy, regulus
import os
vdir = os.path.abspath(sys.argv[1])
regulus.__path__.insert(0, vdir + "/regulus")
import regulus.accuracy.operators as o
assert o.__file__.startswith(vdir), o.__file__
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
