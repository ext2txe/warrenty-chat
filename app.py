from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Optional, Dict, Any, Tuple
import uuid
import datetime
import json
import re

from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "0.1.18"

# ===== APP =====
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ideatect.com",
        "https://www.ideatect.com",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== DATABASE CONFIG =====
# NOTE: keep existing DB URL for drop-in compatibility
DATABASE_URL = "mysql+pymysql://chatuser:StrongPasswordHere@localhost/ideatect"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ===== MODELS =====
class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"
    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), index=True)
    role = Column(String(20))  # "user" or "assistant"
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ConversationMeta(Base):
    __tablename__ = "conversation_meta"
    conversation_id = Column(String(36), primary_key=True)
    state = Column(String(50), default="GET_REFERENCE_ID")
    facts_json = Column(Text, default="{}")

    # Deviation / control
    turns_without_progress = Column(String(10), default="0")
    save_attempt_used = Column(String(10), default="0")

    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


# Create tables if needed (safe on startup)
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


# ===== REQUEST SCHEMA =====
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


@app.get("/")
def root():
    return {"status": "ok", "service": "ideatect-api"}


@app.get("/version")
def version():
    return {"version": APP_VERSION}


# =========================
# Qualification Router Logic
# =========================

DEFAULT_CONFIG = {
    "qualification": {
        "max_vehicle_age_years": 15,   # kept for compatibility (min year rule below takes precedence)
        "max_mileage": 180000,         # NEW: max mileage
        "min_vehicle_year": 2015,      # NEW: min year
        "require_personal_use": True,
        "require_decision_maker": True,
        "require_not_modified": True,
        "require_no_active_issues": True,
    },
    "deviation": {
        "max_turns_without_progress": 2,
        "allow_one_save_attempt": True,
    },
}

CONFIG = DEFAULT_CONFIG

CURRENT_YEAR = datetime.datetime.utcnow().year

# Preconfigured caller name (temporary until policy DB integration)
PRECONFIGURED_CALLER_NAME = "Alex Customer"

REQUIRED_FIELDS = [
    "reference_id",
    "name_confirmed",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "mileage",
    "decision_maker",
    "personal_use",
    "modified",
    "issues_now",
]


def _log_message(db, conversation_id: str, role: str, content: str):
    db.add(
        Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
    )


def _load_facts(meta: ConversationMeta) -> dict:
    try:
        return json.loads(meta.facts_json or "{}")
    except Exception:
        return {}


def _save_facts(meta: ConversationMeta, facts: dict):
    meta.facts_json = json.dumps(facts)


def opening_script() -> str:
    return (
        "Vehicle Service Department, this is Kay in activations. "
        "I’m calling about the coverage notice that was recently mailed out. "
        "To get started, what’s your letter reference number?"
    )


def ask_vehicle() -> str:
    return "Thanks. What’s the year, make, and model of the vehicle?"


def ask_mileage() -> str:
    return "About how many miles are on it? An estimate is fine."


def ask_decision_maker() -> str:
    return "Just to confirm — are you the decision maker for the vehicle? (yes/no)"


def ask_personal_use() -> str:
    return "Just to confirm — is it for personal use (not business/fleet)? (yes/no)"


def ask_modified() -> str:
    return "Just to confirm — is it modified in any major way? (yes/no)"


def ask_issues() -> str:
    return "Just to confirm — are there any mechanical issues or warning lights right now? (yes/no)"


def handoff_payload(reason_codes: list, qualification: Optional[dict] = None) -> dict:
    payload = {"handoff": True, "reason_codes": reason_codes}
    if qualification is not None:
        payload["qualification"] = qualification
    return payload


def normalize_yes_no(t: str) -> Optional[bool]:
    if not t:
        return None
    s = t.strip().lower()
    if re.search(r"\b(y|yes|yeah|yep|correct|that's me|that is me|sure|affirmative)\b", s):
        return True
    if re.search(r"\b(n|no|nope|negative|not me)\b", s):
        return False
    return None


def extract_reference_id(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\b([A-Za-z0-9][A-Za-z0-9\- ]{4,20})\b", text.strip())
    if not m:
        return None
    candidate = m.group(1).strip()
    # reject purely alphabetic short strings like "asd"
    if re.fullmatch(r"[A-Za-z]{1,4}", candidate):
        return None
    return candidate


def validate_year(y: Optional[int]) -> Optional[int]:
    if y is None:
        return None
    if 1980 <= y <= CURRENT_YEAR + 1:
        return y
    return None


def extract_year_make_model(text: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    if not text:
        return None, None, None
    s = re.sub(r"\s+", " ", text.strip())
    year = None
    make = None
    model = None

    m = re.search(r"\b(19[89]\d|20\d{2})\b", s)
    if m:
        try:
            year = int(m.group(1))
        except Exception:
            year = None

    s2 = re.sub(r"\b(19[89]\d|20\d{2})\b", "", s).strip()
    parts = [p for p in s2.split(" ") if p]
    if parts:
        make = parts[0].title()
        if len(parts) > 1:
            model = " ".join(parts[1:]).title()

    return year, make, model


def extract_mileage(text: str) -> Optional[int]:
    if not text:
        return None
    s = text.lower().replace(",", "").strip()

    # handle 42k / 42 k
    m = re.search(r"\b(\d{1,3})\s*k\b", s)
    if m:
        try:
            return int(m.group(1)) * 1000
        except Exception:
            pass

    m = re.search(r"\b(\d{4,6})\b", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    return None


def validate_mileage(m: Optional[int]) -> Optional[int]:
    if m is None:
        return None
    if 0 <= m <= 500000:
        return m
    return None


def derive_state_from_facts(facts: dict) -> str:
    if facts.get("reference_id") is None:
        return "GET_REFERENCE_ID"
    if facts.get("name_confirmed") is None:
        return "GET_NAME_CONFIRMATION"
    if facts.get("vehicle_year") is None or facts.get("vehicle_make") is None or facts.get("vehicle_model") is None:
        return "GET_VEHICLE"
    if facts.get("mileage") is None:
        return "GET_MILEAGE"
    if facts.get("decision_maker") is None:
        return "GET_DECISION_MAKER"
    if facts.get("personal_use") is None:
        return "GET_PERSONAL_USE"
    if facts.get("modified") is None:
        return "GET_MODIFIED"
    if facts.get("issues_now") is None:
        return "GET_ISSUES"
    return "HANDOFF"


def required_complete(facts: dict) -> bool:
    for f in REQUIRED_FIELDS:
        if facts.get(f) is None:
            return False
    return True


def deviation_signals(user_msg: str, facts: dict) -> Dict[str, bool]:
    t = (user_msg or "").lower()
    asked_pricing = any(k in t for k in ["price", "cost", "how much", "$", "payment"])
    asked_coverage = any(k in t for k in ["cover", "coverage", "what does it", "what is included"])
    trust_scam = any(k in t for k in ["scam", "fraud", "legit", "legitimate", "spam", "how did you get"])
    already_have_policy = any(k in t for k in ["already have", "i'm paying", "i paid", "another company", "cancel", "refund", "charge"])
    diagnostic = any(k in t for k in ["check engine", "leak", "leaking", "transmission", "warning", "service message", "broke down", "screen went"])
    confused = any(k in t for k in ["who are you", "where did you get", "i don't understand", "what is this", "not sure what this is"])

    not_dm = any(k in t for k in ["not the decision", "my husband", "my wife", "he's not here", "she's not here", "need to ask", "i'll ask him", "i'll ask her"])

    return {
        "asked_pricing": asked_pricing,
        "asked_coverage_details": asked_coverage,
        "trust_or_scam": trust_scam,
        "already_have_policy": already_have_policy,
        "diagnostic_discussion": diagnostic,
        "confused": confused,
        "not_decision_maker": not_dm or (facts.get("decision_maker") is False),
    }


def apply_rules(facts: dict, cfg: dict):
    qcfg = cfg["qualification"]
    eligible = True
    reason_codes = []

    year = facts.get("vehicle_year")
    mileage = facts.get("mileage")

    # Prefer explicit min year when provided
    min_year = qcfg.get("min_vehicle_year")
    if year is not None and min_year is not None:
        if year < int(min_year):
            eligible = False
            reason_codes.append("year_below_minimum")
    elif year is not None:
        # fallback: max vehicle age
        age = CURRENT_YEAR - year
        if age > qcfg["max_vehicle_age_years"]:
            eligible = False
            reason_codes.append("vehicle_too_old")

    if mileage is not None and mileage > int(qcfg["max_mileage"]):
        eligible = False
        reason_codes.append("mileage_above_maximum")

    if qcfg["require_personal_use"] and facts.get("personal_use") is not True:
        eligible = False
        reason_codes.append("not_personal_use")

    if qcfg["require_decision_maker"] and facts.get("decision_maker") is not True:
        eligible = False
        reason_codes.append("not_decision_maker")

    if qcfg["require_not_modified"] and facts.get("modified") is not False:
        eligible = False
        reason_codes.append("vehicle_modified")

    if qcfg["require_no_active_issues"] and facts.get("issues_now") is not False:
        eligible = False
        reason_codes.append("active_mechanical_issues")

    return {"eligible": eligible, "reason_codes": reason_codes}


def next_question_for_state(state: str, facts: dict) -> str:
    if state == "GET_REFERENCE_ID":
        return opening_script()
    if state == "GET_NAME_CONFIRMATION":
        return f"Thanks. I have this registration under {PRECONFIGURED_CALLER_NAME}. Can you confirm your name? (yes/no)"
    if state == "GET_VEHICLE":
        return ask_vehicle()
    if state == "GET_MILEAGE":
        return ask_mileage()
    if state == "GET_DECISION_MAKER":
        return ask_decision_maker()
    if state == "GET_PERSONAL_USE":
        return ask_personal_use()
    if state == "GET_MODIFIED":
        return ask_modified()
    if state == "GET_ISSUES":
        return ask_issues()
    return "Thanks — you’re all set. I’m going to connect you to an agent now."


def _persist_and_return(db, meta, conversation_id: str, facts: dict, state: str, turns_wo: int, save_used: bool, answer: str, extra: Optional[dict] = None):
    _log_message(db, conversation_id, "assistant", answer)
    meta.state = state
    meta.turns_without_progress = str(turns_wo)
    meta.save_attempt_used = "1" if save_used else "0"
    meta.updated_at = datetime.datetime.utcnow()
    _save_facts(meta, facts)
    db.commit()
    db.close()
    payload = {"conversation_id": conversation_id, "answer": answer, "version": APP_VERSION}
    if extra:
        payload.update(extra)
    return payload


@app.post("/chat")
@app.post("/chat/")
def chat(request: ChatRequest):
    db = SessionLocal()

    # ----- Version command (kept) -----
    if (request.message or "").strip().lower() == "version":
        if not request.conversation_id:
            conversation_id = str(uuid.uuid4())
            db.add(Conversation(id=conversation_id))
            meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
            db.add(meta)
            answer = f"v{APP_VERSION}"
            _log_message(db, conversation_id, "assistant", answer)
            db.commit()
            db.close()
            return {"conversation_id": conversation_id, "answer": answer, "handoff": False, "version": APP_VERSION}

        conversation_id = request.conversation_id
        meta = db.query(ConversationMeta).filter_by(conversation_id=conversation_id).first()
        if not meta:
            meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
            db.add(meta)
        answer = f"v{APP_VERSION}"
        _log_message(db, conversation_id, "assistant", answer)
        db.commit()
        db.close()
        return {"conversation_id": conversation_id, "answer": answer, "handoff": False, "version": APP_VERSION}

    # ----- Create conversation -----
    if not request.conversation_id:
        conversation_id = str(uuid.uuid4())
        db.add(Conversation(id=conversation_id))
        meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
        db.add(meta)

        answer = opening_script()
        _log_message(db, conversation_id, "assistant", answer)
        db.commit()
        db.close()
        return {"conversation_id": conversation_id, "answer": answer, "version": APP_VERSION, "handoff": False}

    # ----- Load meta -----
    conversation_id = request.conversation_id
    meta = db.query(ConversationMeta).filter_by(conversation_id=conversation_id).first()
    if not meta:
        meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
        db.add(meta)

    facts = _load_facts(meta)
    state = meta.state or derive_state_from_facts(facts)

    user_msg = request.message or ""
    _log_message(db, conversation_id, "user", user_msg)

    turns_wo = int(meta.turns_without_progress or "0")
    save_used = (meta.save_attempt_used or "0") == "1"

    # ----- Deviation controls -----
    sig = deviation_signals(user_msg, facts)
    if any([sig["asked_pricing"], sig["asked_coverage_details"], sig["trust_or_scam"], sig["already_have_policy"], sig["diagnostic_discussion"], sig["confused"]]):
        if DEFAULT_CONFIG["deviation"]["allow_one_save_attempt"] and not save_used:
            save_used = True
            answer = "I can help with that — first I just need to confirm a few details from the notice so I can get you to the right person. What’s your letter reference number?"
            return _persist_and_return(
                db, meta, conversation_id, facts, state, turns_wo + 1, save_used, answer,
                extra={"handoff": False}
            )

        answer = "No problem — I’m going to connect you to an agent now."
        return _persist_and_return(
            db, meta, conversation_id, facts, "HANDOFF", turns_wo, True, answer,
            extra=handoff_payload(["deviation_topic"], qualification=None)
        )

    # ==========================================================
    # IMPORTANT BEHAVIOR FIX:
    # Only one “step” per user message. If a step is completed,
    # immediately ask the next question and RETURN.
    # ==========================================================

    # ----- Step: Reference ID -----
    if state == "GET_REFERENCE_ID" and facts.get("reference_id") is None:
        ref = extract_reference_id(user_msg)
        if ref:
            facts["reference_id"] = ref
            turns_wo = 0
            new_state = "GET_NAME_CONFIRMATION"
            answer = next_question_for_state(new_state, facts)
            return _persist_and_return(db, meta, conversation_id, facts, new_state, turns_wo, save_used, answer, extra={"handoff": False})
        else:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(
                    db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer,
                    extra=handoff_payload(["unclear_reference_id"], qualification=None)
                )
            answer = "Sorry — I didn’t catch that. What’s the letter reference number?"
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})

    # ----- Step: Name confirmation -----
    if state == "GET_NAME_CONFIRMATION" and facts.get("name_confirmed") is None:
        yn = normalize_yes_no(user_msg)
        if yn is not None:
            facts["name_confirmed"] = yn
            turns_wo = 0
            if yn is True:
                new_state = "GET_VEHICLE"
                answer = next_question_for_state(new_state, facts)
                return _persist_and_return(db, meta, conversation_id, facts, new_state, turns_wo, save_used, answer, extra={"handoff": False})
            else:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(
                    db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer,
                    extra=handoff_payload(["name_not_confirmed"], qualification=None)
                )

        turns_wo += 1
        if turns_wo >= 2:
            answer = "No problem — I’m going to connect you to an agent now."
            return _persist_and_return(
                db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer,
                extra=handoff_payload(["unclear_name_confirmation"], qualification=None)
            )
        answer = f"Sorry — I just need a yes or no. Is your name {PRECONFIGURED_CALLER_NAME}? (yes/no)"
        return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})

    # ----- Step: Vehicle year/make/model -----
    if state == "GET_VEHICLE":
        year, make, model = extract_year_make_model(user_msg)
        year = validate_year(year) if year is not None else None

        if year is not None:
            facts["vehicle_year"] = year
        if make:
            facts["vehicle_make"] = make
        if model:
            facts["vehicle_model"] = model

        # If still incomplete, re-ask vehicle question (don't handoff immediately)
        if facts.get("vehicle_year") is None or facts.get("vehicle_make") is None or facts.get("vehicle_model") is None:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(
                    db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer,
                    extra=handoff_payload(["missing_vehicle_info"], qualification=None)
                )
            answer = "Sorry — I just need the year, make, and model (example: 2021 Ford Fiesta). What’s the year, make, and model?"
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})

        # Early disqualify on year (min year 2015)
        decision = apply_rules(facts, DEFAULT_CONFIG)
        if not decision["eligible"] and "year_below_minimum" in decision["reason_codes"]:
            answer = "Thanks — based on the vehicle year, it looks like this vehicle doesn’t meet the eligibility criteria. I’m going to connect you to an agent to go over options."
            return _persist_and_return(
                db, meta, conversation_id, facts, "HANDOFF", 0, save_used, answer,
                extra=handoff_payload(["not_eligible"] + decision["reason_codes"], qualification=decision)
            )

        # Move to mileage
        new_state = "GET_MILEAGE"
        answer = next_question_for_state(new_state, facts)
        return _persist_and_return(db, meta, conversation_id, facts, new_state, 0, save_used, answer, extra={"handoff": False})

    # ----- Step: Mileage (STRICT: only in GET_MILEAGE) -----
    if state == "GET_MILEAGE":
        miles = extract_mileage(user_msg)
        miles = validate_mileage(miles) if miles is not None else None

        if miles is None:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(
                    db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer,
                    extra=handoff_payload(["unclear_mileage"], qualification=None)
                )
            answer = "Sorry — about how many miles are on it? You can reply like “42000” or “42k”."
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})

        facts["mileage"] = miles

        # Early disqualify on mileage (max 180k)
        decision = apply_rules(facts, DEFAULT_CONFIG)
        if not decision["eligible"] and "mileage_above_maximum" in decision["reason_codes"]:
            answer = "Thanks — based on the mileage, it looks like this vehicle doesn’t meet the eligibility criteria. I’m going to connect you to an agent to go over options."
            return _persist_and_return(
                db, meta, conversation_id, facts, "HANDOFF", 0, save_used, answer,
                extra=handoff_payload(["not_eligible"] + decision["reason_codes"], qualification=decision)
            )

        new_state = "GET_DECISION_MAKER"
        answer = next_question_for_state(new_state, facts)
        return _persist_and_return(db, meta, conversation_id, facts, new_state, 0, save_used, answer, extra={"handoff": False})

    # ----- Remaining yes/no steps -----
    yn = normalize_yes_no(user_msg)

    if state == "GET_DECISION_MAKER":
        if yn is None:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer, extra=handoff_payload(["unclear_decision_maker"], qualification=None))
            answer = "Sorry — just yes or no: are you the decision maker for the vehicle? (yes/no)"
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})
        facts["decision_maker"] = yn
        new_state = "GET_PERSONAL_USE"
        answer = next_question_for_state(new_state, facts)
        return _persist_and_return(db, meta, conversation_id, facts, new_state, 0, save_used, answer, extra={"handoff": False})

    if state == "GET_PERSONAL_USE":
        if yn is None:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer, extra=handoff_payload(["unclear_personal_use"], qualification=None))
            answer = "Sorry — just yes or no: is it for personal use (not business/fleet)? (yes/no)"
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})
        facts["personal_use"] = yn
        new_state = "GET_MODIFIED"
        answer = next_question_for_state(new_state, facts)
        return _persist_and_return(db, meta, conversation_id, facts, new_state, 0, save_used, answer, extra={"handoff": False})

    if state == "GET_MODIFIED":
        if yn is None:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer, extra=handoff_payload(["unclear_modified"], qualification=None))
            answer = "Sorry — just yes or no: is it modified in any major way? (yes/no)"
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})
        facts["modified"] = yn
        new_state = "GET_ISSUES"
        answer = next_question_for_state(new_state, facts)
        return _persist_and_return(db, meta, conversation_id, facts, new_state, 0, save_used, answer, extra={"handoff": False})

    if state == "GET_ISSUES":
        if yn is None:
            turns_wo += 1
            if turns_wo >= 2:
                answer = "No problem — I’m going to connect you to an agent now."
                return _persist_and_return(db, meta, conversation_id, facts, "HANDOFF", turns_wo, save_used, answer, extra=handoff_payload(["unclear_issues_now"], qualification=None))
            answer = "Sorry — just yes or no: any mechanical issues or warning lights right now? (yes/no)"
            return _persist_and_return(db, meta, conversation_id, facts, state, turns_wo, save_used, answer, extra={"handoff": False})
        facts["issues_now"] = yn

        # Done -> handoff
        decision = apply_rules(facts, DEFAULT_CONFIG)
        reason_codes = ["qualified"] if decision["eligible"] else ["not_eligible"] + decision["reason_codes"]
        answer = "Thanks — you’re all set. I’m going to connect you to an agent now."
        return _persist_and_return(
            db, meta, conversation_id, facts, "HANDOFF", 0, save_used, answer,
            extra=handoff_payload(reason_codes, qualification=decision)
        )

    # Fallback (should be rare)
    new_state = derive_state_from_facts(facts)
    answer = next_question_for_state(new_state, facts)
    return _persist_and_return(db, meta, conversation_id, facts, new_state, turns_wo, save_used, answer, extra={"handoff": False})
