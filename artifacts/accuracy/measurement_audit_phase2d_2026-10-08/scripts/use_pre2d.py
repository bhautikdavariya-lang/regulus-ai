"""Run a script with regulus.accuracy taken from the reconstructed pre-Phase-2D copy."""
import sys, runpy, regulus
regulus.__path__.insert(0, "/private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/e3d73475-541b-4393-a7bb-0894f3bb6d71/scratchpad/pre2d/only/regulus")
import regulus.accuracy.verdicts as v
assert v.__file__.startswith("/private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/e3d73475-541b-4393-a7bb-0894f3bb6d71/scratchpad/pre2d/only"), v.__file__
script = sys.argv[1]; sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
