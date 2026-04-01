from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class ExtractionField:
    name: str
    field_type: str
    description: str
    required: bool = False
    confirmation_required: bool = False


@dataclass
class ExtractionResult:
    extractor: str
    source: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    raw_response: Optional[str] = None


@dataclass
class WorkflowContext:
    config: Dict[str, Any]
    caller_name: str
    input_mode: str = "text"
    transcript_confidence: Optional[float] = None
    transcript_is_final: bool = True
    transcript_is_partial: bool = False


@dataclass
class TurnResult:
    state: str
    facts: Dict[str, Any]
    answer: str
    handoff: bool = False
    reason_codes: List[str] = field(default_factory=list)
    qualification: Optional[Dict[str, Any]] = None
    turns_without_progress: int = 0
    save_attempt_used: bool = False
    extraction: Optional[ExtractionResult] = None


class WorkflowPlugin(Protocol):
    name: str
    initial_state: str
    extraction_schema: Dict[str, List[ExtractionField]]

    def get_opening_message(self, context: WorkflowContext) -> str:
        ...

    def derive_state_from_facts(self, facts: Dict[str, Any]) -> str:
        ...

    def next_question_for_state(self, state: str, facts: Dict[str, Any], context: WorkflowContext) -> str:
        ...

    def handle_turn(
        self,
        user_msg: str,
        facts: Dict[str, Any],
        state: str,
        turns_without_progress: int,
        save_attempt_used: bool,
        context: WorkflowContext,
        extractor: Any,
    ) -> TurnResult:
        ...


class ConversationEngine:
    def __init__(self, workflows: Dict[str, WorkflowPlugin], default_workflow: str, extractor: Any):
        self.workflows = workflows
        self.default_workflow = default_workflow
        self.extractor = extractor

    def get_workflow(self, workflow_name: Optional[str] = None) -> WorkflowPlugin:
        key = workflow_name or self.default_workflow
        return self.workflows[key]

    def start_conversation(self, workflow_name: Optional[str], context: WorkflowContext) -> TurnResult:
        workflow = self.get_workflow(workflow_name)
        return TurnResult(
            state=workflow.initial_state,
            facts={},
            answer=workflow.get_opening_message(context),
            handoff=False,
            turns_without_progress=0,
            save_attempt_used=False,
        )

    def process_turn(
        self,
        workflow_name: Optional[str],
        user_msg: str,
        facts: Dict[str, Any],
        state: Optional[str],
        turns_without_progress: int,
        save_attempt_used: bool,
        context: WorkflowContext,
    ) -> TurnResult:
        workflow = self.get_workflow(workflow_name)
        active_state = state or workflow.derive_state_from_facts(facts)
        return workflow.handle_turn(
            user_msg=user_msg,
            facts=facts,
            state=active_state,
            turns_without_progress=turns_without_progress,
            save_attempt_used=save_attempt_used,
            context=context,
            extractor=self.extractor,
        )
