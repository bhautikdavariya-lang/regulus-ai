"""Stage 5: comprehensive, layer-separated evaluation of the Regulus pipeline.

Public surface:
    load_stage5_dataset, Stage5Example, Stage5Dataset
    run_stage5(run_dir, ...)          evidence -> generation -> reports, resumable
    build_reports(...)                regenerate the metric files and report from a finished run
    stage5_completed(run_dir)
"""

from regulus.stage5.dataset import Stage5Dataset, Stage5DatasetError, Stage5Example, load_stage5_dataset
from regulus.stage5.runner import Stage5Error, build_reports, run_stage5, stage5_completed

__all__ = ["Stage5Dataset", "Stage5DatasetError", "Stage5Error", "Stage5Example", "build_reports", "load_stage5_dataset", "run_stage5", "stage5_completed"]
