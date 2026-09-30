"""Stage 6: the controlled fine-tuning experiment.

Two responsibilities live here and nothing else:

    prompting   render a training example with the Stage 4 generation contract,
                so the model is trained on the interface it meets at inference
    generators  multi-provision, range and partial (proven-absent) examples,
                the behaviours Stage 5 measures and earlier datasets lacked

Training itself reuses regulus.finetune (LoRA/PEFT) unchanged.
"""

from regulus.stage6.generators import (
    FAMILY,
    STAGE6_GENERATORS,
    children_of,
    find_absent_child,
    gen_multi_provision,
    gen_partial_provision,
    gen_range_provision,
    numbered_groups,
    present_paragraph_paths,
)
from regulus.stage6.prompting import example_package, to_grounded_messages

__all__ = [
    "FAMILY",
    "STAGE6_GENERATORS",
    "children_of",
    "example_package",
    "find_absent_child",
    "gen_multi_provision",
    "gen_partial_provision",
    "gen_range_provision",
    "numbered_groups",
    "present_paragraph_paths",
    "to_grounded_messages",
]
