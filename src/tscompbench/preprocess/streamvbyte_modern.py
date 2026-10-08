"""Exact modern backend stage specification; legacy and modern IDs stay distinct."""

from __future__ import annotations

from copy import deepcopy

from tscompbench.ids import stable_id

from .streamvbyte import STAGE_SPEC as LEGACY_STAGES

STAGE_SPEC = deepcopy(LEGACY_STAGES)
STAGE_SPEC[2]["name"] = "MODERN_STREAM_VBYTE_1234_SSE41"
EXECUTOR_ID = stable_id(
    "pipeline-executor",
    {
        "version": "streamvbyte-modern-stages-v1",
        "stages": STAGE_SPEC,
        "source": "fast-pack/streamvbyte@7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce",
        "count_placement": "SHIM_COUNT_U32_OUTSIDE_NATIVE_API_TIMING",
        "disabled_A": "ORIGINAL_INT64_BITS",
        "disabled_B": "BYTE_PRESERVING_LE_U32_VIEW",
        "disabled_C": "COUNT_U32_AND_RAW_LE_WORDS",
        "disabled_D": "NOT_SELF_CONTAINED_REJECTED",
    },
)
