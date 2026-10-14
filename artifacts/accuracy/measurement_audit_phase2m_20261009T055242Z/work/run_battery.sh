#!/bin/bash
# Phase 2M regression battery per variant (offline; read-only DB via the variant loader). Usage: run_battery.sh <variant>...
D=artifacts/accuracy/measurement_audit_phase2m_20261009T055242Z/work; PY=.venv/bin/python
for v in "$@"; do
  {
  echo "#### $v"
  $PY $D/run_suite_variant.py $D/variants/$v --runxfail 2>&1 | grep -E "^FAILED|passed|failed" | tail -8
  for s in eval_real_controls eval_diagnostics eval_numeric eval_controls_h eval_m_cases; do $PY $D/use_variant_ro.py $D/variants/$v $D/$s.py $D/.. $v 2>&1 | grep -v Warn | tail -1; done
  $PY $D/use_variant_ro.py $D/variants/$v $D/numeric_probes.py $D $v 2>&1 | grep -c "^ok " | sed 's/^/probes ok: /'
  $PY $D/use_variant_ro.py $D/variants/$v $D/collect_h.py $D/h_cf_$v.json 2>&1 | grep -v Warn | tail -1
  } > $D/battery_$v.log 2>&1
done
