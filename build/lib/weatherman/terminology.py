from __future__ import annotations

from collections.abc import Mapping


CHECKPOINT_LABELS: Mapping[str, str] = {
    "d1": "D−1 @20 LT",
    "d0_06": "D0 @06 LT",
    "d0_10": "D0 @10 LT",
    "live": "First stored live snapshot after D0@10",
}

FORECAST_STAGE_LABELS: Mapping[str, str] = {
    "raw": "Raw ensemble",
    "bias": "Bias-corrected",
    "metar": "Live weather-adjusted",
    "champion": "Champion",
    "taf": "TAF guidance",
}

EVIDENCE_GLOSSARY: Mapping[str, str] = {
    "scheduled": (
        "A real production snapshot stored at the intended checkpoint from information "
        "available at that time. Scheduled does not by itself guarantee fresh sources."
    ),
    "reconstructed": (
        "Rebuilt later from guidance proven available before the checkpoint. It is useful "
        "for research, but is not genuine live/OOS evidence."
    ),
    "late/post-peak": (
        "Stored only after the intended trading time or after the modelled peak. It remains "
        "diagnostic and is excluded from timing-reliability claims."
    ),
    "missing": "No defensible forecast snapshot is available for this checkpoint.",
}

FRESHNESS_GLOSSARY: Mapping[str, str] = {
    "fresh": "All Champion-relevant sources are at most 30 minutes old.",
    "aging": "The oldest Champion-relevant source is 31–90 minutes old.",
    "stale": "At least one Champion-relevant source is more than 90 minutes old.",
    "unavailable": "Source age cannot be established or no relevant source is available.",
}


def checkpoint_stage_label(prefix: str, stage: str) -> str:
    """Return one canonical timepoint + forecast-stage display label."""
    return f"{CHECKPOINT_LABELS[prefix]} · {FORECAST_STAGE_LABELS[stage]}"

