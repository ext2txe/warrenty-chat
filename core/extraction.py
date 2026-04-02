from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.workflow import ExtractionResult, WorkflowContext


COMMON_MAKES = {
    "acura", "alfa", "alfa romeo", "audi", "bmw", "buick", "cadillac", "chevrolet", "chevy",
    "chrysler", "dodge", "fiat", "ford", "gmc", "genesis", "honda", "hyundai", "infiniti",
    "jaguar", "jeep", "kia", "land rover", "lexus", "lincoln", "mazda", "mercedes",
    "mercedes-benz", "mini", "mitsubishi", "nissan", "porsche", "ram", "subaru", "tesla",
    "toyota", "volkswagen", "vw", "volvo",
}

FILLER_PHRASES = [
    "it is", "it's", "its", "i have", "i drive", "we have", "the vehicle is", "vehicle is",
    "car is", "truck is", "my car is", "my truck is", "my vehicle is", "it was", "this is",
]

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _clean_text(text: str) -> str:
    sample = re.sub(r"\s+", " ", (text or "").strip())
    for phrase in FILLER_PHRASES:
        sample = re.sub(rf"\b{re.escape(phrase)}\b", "", sample, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", sample).strip(" ,.-")


def _normalize_make(raw_make: str) -> str:
    aliases = {
        "chevy": "Chevrolet",
        "vw": "Volkswagen",
        "mercedes-benz": "Mercedes-Benz",
    }
    lowered = raw_make.lower()
    if lowered in aliases:
        return aliases[lowered]
    return " ".join(word.capitalize() for word in raw_make.split())


def normalize_yes_no(text: str) -> Optional[bool]:
    return extract_name_confirmation(text)


def extract_name_confirmation(text: str) -> Optional[bool]:
    if not text:
        return None
    sample = text.strip().lower()
    positive_patterns = [
        r"\b(y|yes|yeah|yep|correct|sure|affirmative|that'?s me|that is me|this is (him|her)|speaking)\b",
    ]
    negative_patterns = [
        r"\b(n|no|nope|negative|not me|wrong person|wrong number|you have the wrong)\b",
    ]
    for pattern in positive_patterns:
        if re.search(pattern, sample):
            return True
    for pattern in negative_patterns:
        if re.search(pattern, sample):
            return False
    return None


def extract_decision_maker(text: str) -> Optional[bool]:
    if not text:
        return None
    sample = text.strip().lower()
    positive_patterns = [
        r"\b(y|yes|yeah|yep|i am|that would be me|i handle that|i make that decision)\b",
    ]
    negative_patterns = [
        r"\b(n|no|nope|not me|my (wife|husband|spouse|partner|dad|mom|mother|father) handles|need to ask|have to ask)\b",
    ]
    for pattern in positive_patterns:
        if re.search(pattern, sample):
            return True
    for pattern in negative_patterns:
        if re.search(pattern, sample):
            return False
    return None


def extract_personal_use(text: str) -> Optional[bool]:
    if not text:
        return None
    sample = text.strip().lower()
    positive_patterns = [
        r"\b(y|yes|yeah|yep|personal|just me|family car|daily driver|commute)\b",
    ]
    negative_patterns = [
        r"\b(n|no|nope|business|work truck|company vehicle|fleet|commercial|uber|lyft|delivery)\b",
    ]
    for pattern in positive_patterns:
        if re.search(pattern, sample):
            return True
    for pattern in negative_patterns:
        if re.search(pattern, sample):
            return False
    return None


def extract_modified(text: str) -> Optional[bool]:
    if not text:
        return None
    sample = text.strip().lower()
    negative_patterns = [
        r"\b(n|no|nope|stock|all stock|nothing major|factory|original)\b",
    ]
    positive_patterns = [
        r"\b(y|yes|yeah|yep|modified|lift kit|lowered|tuned|aftermarket|supercharger|turbo kit|oversized tires)\b",
    ]
    for pattern in negative_patterns:
        if re.search(pattern, sample):
            return False
    for pattern in positive_patterns:
        if re.search(pattern, sample):
            return True
    return None


def extract_issues_now(text: str) -> Optional[bool]:
    if not text:
        return None
    sample = text.strip().lower()
    negative_patterns = [
        r"\b(n|no|nope|none|runs fine|runs great|drives fine|no issues|no warning lights|nothing wrong)\b",
    ]
    positive_patterns = [
        r"\b(y|yes|yeah|yep|check engine|warning light|mechanical issue|problem|leak|leaking|slipping|misfire|overheating|broke down)\b",
    ]
    for pattern in negative_patterns:
        if re.search(pattern, sample):
            return False
    for pattern in positive_patterns:
        if re.search(pattern, sample):
            return True
    return None


def extract_reference_id(text: str) -> Optional[str]:
    if not text:
        return None
    sample = text.strip()
    patterns = [
        r"(?:reference|ref|letter|mailer|id|number)\s*(?:number|#|is|:|-)?\s*([A-Za-z0-9][A-Za-z0-9\-]{2,19})\b",
        r"\b([A-Za-z]{1,4}-?\d{3,10})\b",
        r"\b(\d{5,12})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, sample, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().upper()
            if candidate in {"REFERENCE", "NUMBER", "LETTER", "MAILER"}:
                continue
            return candidate
    return None


def extract_year_make_model(text: str) -> Dict[str, Any]:
    if not text:
        return {}

    sample = _clean_text(text)
    year = None
    make = None
    model = None

    match = re.search(r"\b(19[89]\d|20\d{2})\b", sample)
    if match:
        try:
            year = int(match.group(1))
        except Exception:
            year = None

    remainder = re.sub(r"\b(19[89]\d|20\d{2})\b", "", sample).strip(" ,.-")
    remainder = re.sub(r"[^\w\s/&-]", " ", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip()
    remainder = re.sub(r"^(a|an|the)\s+", "", remainder, flags=re.IGNORECASE)
    parts = [part for part in remainder.split(" ") if part]
    if parts:
        two_word_make = " ".join(parts[:2]).lower() if len(parts) >= 2 else None
        first_part = parts[0].lower()
        if two_word_make and two_word_make in COMMON_MAKES:
            make = _normalize_make(" ".join(parts[:2]))
            model_parts = parts[2:]
        else:
            make = _normalize_make(parts[0])
            model_parts = parts[1:]
        if make.lower() not in COMMON_MAKES and first_part not in COMMON_MAKES:
            make = _normalize_make(parts[0])
        if model_parts:
            model = " ".join(token.capitalize() if token.isalpha() else token.upper() for token in model_parts)

    return {
        "vehicle_year": year,
        "vehicle_make": make,
        "vehicle_model": model,
    }


def extract_number_words(text: str) -> Optional[int]:
    if not text:
        return None
    sample = text.lower().replace("-", " ")
    sample = re.sub(r"[^a-z\s]", " ", sample)
    tokens = [token for token in sample.split() if token]
    if not tokens:
        return None

    total = 0
    current = 0
    seen = False
    for token in tokens:
        if token in NUMBER_WORDS:
            current += NUMBER_WORDS[token]
            seen = True
            continue
        if token == "hundred":
            if current == 0:
                current = 1
            current *= 100
            seen = True
            continue
        if token == "thousand":
            if current == 0:
                current = 1
            total += current * 1000
            current = 0
            seen = True
            continue
        if seen:
            break

    value = total + current
    return value if seen and value > 0 else None


def extract_mileage(text: str) -> Optional[int]:
    if not text:
        return None

    sample = text.lower().replace(",", "").strip()

    match = re.search(r"\b(?:about|around|roughly|approximately|maybe|like)?\s*(\d{1,3}(?:\.\d)?)\s*k\b", sample)
    if match:
        try:
            return int(float(match.group(1)) * 1000)
        except Exception:
            return None

    match = re.search(r"\b(\d{4,6})\s*(?:miles?)?\b", sample)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None

    if "thousand" in sample:
        number_words = extract_number_words(sample)
        if number_words is not None:
            return number_words

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
        elif state in {"GET_NAME_CONFIRMATION", "CONFIRM_REFERENCE_ID", "CONFIRM_VEHICLE"}:
            data["name_confirmed"] = extract_name_confirmation(user_msg)
        elif state == "GET_VEHICLE":
            data.update(extract_year_make_model(user_msg))
        elif state == "GET_MILEAGE":
            data["mileage"] = extract_mileage(user_msg)
        elif state == "GET_DECISION_MAKER":
            data["decision_maker"] = extract_decision_maker(user_msg)
        elif state == "GET_PERSONAL_USE":
            data["personal_use"] = extract_personal_use(user_msg)
        elif state == "GET_MODIFIED":
            data["modified"] = extract_modified(user_msg)
        elif state == "GET_ISSUES":
            data["issues_now"] = extract_issues_now(user_msg)

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
