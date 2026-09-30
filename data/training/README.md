# Training data (Stage 11)

Instruction-tuning examples generated from the read-only `regulus`
database. Full description: `docs/training_data_preparation.md`.

```
data/training/datasets/
  training_v1.jsonl      train split   (generated, gitignored)
  validation_v1.jsonl    validation    (generated, gitignored)
  test_v1.jsonl          test          (generated, gitignored)
  manifest_v1.json       config, snapshot facts, counts, per-file and dataset SHA-256 (tracked)
  validation_v1.json     last validation report (tracked)
```

Regenerate (deterministic; identical files for the same snapshot and seed):

```powershell
python scripts/prepare_training_data.py            # ~40 s, reads the database only
python scripts/validate_training_data.py           # re-verifies provenance against the database
python scripts/report_training_data.py --samples 2
```

Options: `--target N`, `--seed N`, `--version vX`, `--output-dir DIR`,
`--config PATH`; the category shares and quality filters live in
`configs/training.yaml`.

One JSON object per line; see the schema in the docs. `grounded: true`
examples cite their context; `type: "abstention"` examples refuse and carry
no citations. Never edit these files by hand: change the generator or the
config and regenerate, then validate.

The evaluation benchmarks in `data/evaluation/datasets/` are excluded from
this data and must stay untouched; they measure whether training helped.
