from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.workflow import ExtractionResult, WorkflowContext


def normalize_yes_no(text: str) -> Optional[bool]:
    if not text:
        return None
    sample = text.strip().lower()
    if re.search(r"\b(y|yes|yeah|yep|correct|that's me|that is me|sure|affirmative)\b", sample):
        return True
    if re.search(r"\b(n|no|nope|negative|not me)\b", sample):
        return False
    return None


def extract_reference_id(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"\b([A-Za-z0-9][A-Za-z0-9\- ]{4,20})\b", text.strip())
    if not match:
        return None
    candidate = match.group(1).strip()
    if re.fullmatch(r"[A-Za-z]{1,4}", candidate):
        return None
    return candidate


def extract_year_make_model(text: str) -> Dict[str, Any]:
    if not text:
        return {}

    sample = re.sub(r"\s+", " ", text.strip())
    year = None
    make = None
    model = None

    match = re.search(r"\b(19[89]\d|20\d{2})\b", sample)
    if match:
        try:
            year = int(match.group(1))
        except Exception:
            year = None

    remainder = re.sub(r"\b(19[89]\d|20\d{2})\b", "", sample).strip()
    parts = [part for part in remainder.split(" ") if part]
    if parts:
        make = parts[0].title()
        if len(parts) > 1:
            model = " ".join(parts[1:]).title()

    return {
        "vehicle_year": year,
        "vehicle_make": make,
        "vehicle_model": model,
    }


def extract_mileage(text: str) -> Optional[int]:
    if not text:
        return None

    sample = text.lower().replace(",", "").strip()

    match = re.search(r"\b(\d{1,3})\s*k\b", sample)
    if match:
        try:
            return int(match.group(1)) * 1000
        except Exception:
            return None

    match = re.search(r"\b(\d{4,6})\b", sample)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None

    return None


class RegexFallbackExtractor:
    name = "regex_fallback"

    def extract(self, workflow: Any, state: str, user_msg: str, facts: Dict[str, Any], context: WorkflowContext) -> ExtractionResult:
        data: Dict[str, Any] = {
            "input_mode": context.input_mode,
            "transcript_confidence": context.transcript_confidence,
            "transcript_is_final": context.transcript_is_final,
            "transcript_is_partial": context.transcript_is_partial,
        }

        if state == "GET_REFERENCE_ID":
            data["reference_id"] = extract_reference_id(user_msg)
        elif state == "GET_NAME_CONFIRMATION":
            data["name_confirmed"] = normalize_yes_no(user_msg)
        elif state == "GET_VEHICLE":
            data.update(extract_year_make_model(user_msg))
        elif state == "GET_MILEAGE":
            data["mileage"] = extract_mileage(user_msg)
        elif state == "GET_DECISION_MAKER":
            data["decision_maker"] = normalize_yes_no(user_msg)
        elif state == "GET_PERSONAL_USE":
            data["personal_use"] = normalize_yes_no(user_msg)
        elif state == "GET_MODIFIED":
            data["modified"] = normalize_yes_no(user_msg)
        elif state == "GET_ISSUES":
            data["issues_now"] = normalize_yes_no(user_msg)

        populated = any(
            value is not None
            for key, value in data.items()
            if key not in {"input_mode", "transcript_confidence", "transcript_is_final", "transcript_is_partial"}
        )
        return ExtractionResult(
            extractor=self.name,
            source="fallback",
            success=populated,
            data=data,
            errors=[] if populated else ["no_fields_extracted"],
        )


class HybridExtractionLayer:
    """
    Model-first extraction hook point with a deterministic regex fallback.

    The model path is intentionally left as a future extension point; the
    workflow engine already expects strict structured data from this layer.
    """

    def __init__(self, fallback: Optional[RegexFallbackExtractor] = None):
        self.fallback = fallback or RegexFallbackExtractor()

    def extract(self, workflow: Any, state: str, user_msg: str, facts: Dict[str, Any], context: WorkflowContext) -> ExtractionResult:
        return self.fallback.extract(workflow, state, user_msg, facts, context)
