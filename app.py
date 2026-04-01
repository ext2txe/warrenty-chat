import datetime
import json
import uuid
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from core.extraction import HybridExtractionLayer
from core.workflow import ConversationEngine, WorkflowContext
from workflows.warranty_qualification import DEFAULT_CONFIG, WarrantyQualificationWorkflow


APP_VERSION = "0.1.21"
DATABASE_URL = "mysql+pymysql://chatuser:StrongPasswordHere@localhost/ideatect"
PRECONFIGURED_CALLER_NAME = "Alex Customer"
DEFAULT_WORKFLOW = "warranty_qualification"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

conversation_engine = ConversationEngine(
    workflows={DEFAULT_WORKFLOW: WarrantyQualificationWorkflow(DEFAULT_CONFIG)},
    default_workflow=DEFAULT_WORKFLOW,
    extractor=HybridExtractionLayer(),
)

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


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"
    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), index=True)
    role = Column(String(20))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ConversationMeta(Base):
    __tablename__ = "conversation_meta"
    conversation_id = Column(String(36), primary_key=True)
    state = Column(String(50), default="GET_REFERENCE_ID")
    facts_json = Column(Text, default="{}")
    turns_without_progress = Column(String(10), default="0")
    save_attempt_used = Column(String(10), default="0")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class ExtractionEvent(Base):
    __tablename__ = "extraction_events"
    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), index=True)
    workflow_name = Column(String(100), default=DEFAULT_WORKFLOW)
    state = Column(String(50))
    raw_text = Column(Text)
    extractor = Column(String(100))
    source = Column(String(50))
    success = Column(Boolean, default=False)
    structured_json = Column(Text, default="{}")
    errors_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    input_mode: str = "text"
    transcript_confidence: Optional[float] = None
    transcript_is_final: bool = True
    transcript_is_partial: bool = False


def _log_message(db, conversation_id: str, role: str, content: str):
    db.add(Message(id=str(uuid.uuid4()), conversation_id=conversation_id, role=role, content=content))


def _log_extraction_event(db, conversation_id: str, workflow_name: str, state: str, raw_text: str, extraction):
    if extraction is None:
        return
    db.add(
        ExtractionEvent(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            workflow_name=workflow_name,
            state=state,
            raw_text=raw_text,
            extractor=extraction.extractor,
            source=extraction.source,
            success=bool(extraction.success),
            structured_json=json.dumps(extraction.data),
            errors_json=json.dumps(extraction.errors),
        )
    )


def _load_facts(meta: ConversationMeta) -> dict:
    try:
        return json.loads(meta.facts_json or "{}")
    except Exception:
        return {}


def _save_facts(meta: ConversationMeta, facts: dict):
    meta.facts_json = json.dumps(facts)


def _workflow_context(request: ChatRequest) -> WorkflowContext:
    return WorkflowContext(
        config=DEFAULT_CONFIG,
        caller_name=PRECONFIGURED_CALLER_NAME,
        input_mode=request.input_mode or "text",
        transcript_confidence=request.transcript_confidence,
        transcript_is_final=bool(request.transcript_is_final),
        transcript_is_partial=bool(request.transcript_is_partial),
    )


def _persist_and_return(
    db,
    meta,
    conversation_id: str,
    result,
    workflow_name: str,
    raw_text: Optional[str] = None,
    processed_state: Optional[str] = None,
):
    if raw_text is not None:
        _log_extraction_event(db, conversation_id, workflow_name, processed_state or result.state, raw_text, result.extraction)

    _log_message(db, conversation_id, "assistant", result.answer)
    meta.state = result.state
    meta.turns_without_progress = str(result.turns_without_progress)
    meta.save_attempt_used = "1" if result.save_attempt_used else "0"
    meta.updated_at = datetime.datetime.utcnow()
    _save_facts(meta, result.facts)
    db.commit()
    db.close()

    payload = {
        "conversation_id": conversation_id,
        "answer": result.answer,
        "version": APP_VERSION,
        "handoff": result.handoff,
    }
    if result.reason_codes:
        payload["reason_codes"] = result.reason_codes
    if result.qualification is not None:
        payload["qualification"] = result.qualification
    return payload


@app.get("/")
def root():
    return {"status": "ok", "service": "ideatect-api"}


@app.get("/version")
def version():
    return {"version": APP_VERSION}


@app.post("/chat")
@app.post("/chat/")
def chat(request: ChatRequest):
    db = SessionLocal()
    workflow_name = DEFAULT_WORKFLOW
    context = _workflow_context(request)

    if (request.message or "").strip().lower() == "version":
        if not request.conversation_id:
            conversation_id = str(uuid.uuid4())
            db.add(Conversation(id=conversation_id))
            meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
            db.add(meta)
        else:
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

    if not request.conversation_id:
        conversation_id = str(uuid.uuid4())
        db.add(Conversation(id=conversation_id))
        meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
        db.add(meta)
        result = conversation_engine.start_conversation(workflow_name, context)
        return _persist_and_return(db, meta, conversation_id, result, workflow_name)

    conversation_id = request.conversation_id
    meta = db.query(ConversationMeta).filter_by(conversation_id=conversation_id).first()
    if not meta:
        meta = ConversationMeta(conversation_id=conversation_id, state="GET_REFERENCE_ID")
        db.add(meta)

    facts = _load_facts(meta)
    user_msg = request.message or ""
    _log_message(db, conversation_id, "user", user_msg)

    result = conversation_engine.process_turn(
        workflow_name=workflow_name,
        user_msg=user_msg,
        facts=facts,
        state=meta.state,
        turns_without_progress=int(meta.turns_without_progress or "0"),
        save_attempt_used=(meta.save_attempt_used or "0") == "1",
        context=context,
    )
    return _persist_and_return(db, meta, conversation_id, result, workflow_name, raw_text=user_msg, processed_state=meta.state)
