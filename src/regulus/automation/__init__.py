"""Unattended Stage 5 / Stage 6 automation: logging, resource checks, phase markers."""

from regulus.automation.log import (
    PipelineLog,
    ResourceError,
    append_jsonl,
    ensure_resources,
    new_run_id,
    read_json,
    read_jsonl,
    resource_report,
    write_json,
)

__all__ = ["PipelineLog", "ResourceError", "append_jsonl", "ensure_resources", "new_run_id", "read_json", "read_jsonl", "resource_report", "write_json"]
