from __future__ import annotations

import datetime
from copy import deepcopy
from typing import Any, Dict, List, Optional

from core.workflow import ExtractionField, TurnResult, WorkflowContext


CURRENT_YEAR = datetime.datetime.utcnow().year


DEFAULT_CONFIG = {
    "qualification": {
        "max_vehicle_age_years": 15,
        "max_mileage": 180000,
        "min_vehicle_year": 2015,
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


class WarrantyQualificationWorkflow:
    name = "warranty_qualification"
    initial_state = "GET_REFERENCE_ID"
    required_fields = [
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
    extraction_schema = {
        "GET_REFERENCE_ID": [
            ExtractionField("reference_id", "string", "Letter or mailer reference identifier", required=True, confirmation_required=True),
        ],
        "GET_NAME_CONFIRMATION": [
            ExtractionField("name_confirmed", "boolean", "Whether the caller confirmed the preconfigured name", required=True),
        ],
        "GET_VEHICLE": [
            ExtractionField("vehicle_year", "integer", "Vehicle year", required=True, confirmation_required=True),
            ExtractionField("vehicle_make", "string", "Vehicle make", required=True),
            ExtractionField("vehicle_model", "string", "Vehicle model", required=True),
        ],
        "GET_MILEAGE": [
            ExtractionField("mileage", "integer", "Vehicle mileage", required=True, confirmation_required=True),
        ],
        "GET_DECISION_MAKER": [
            ExtractionField("decision_maker", "boolean", "Whether the speaker is the decision maker", required=True),
        ],
        "GET_PERSONAL_USE": [
            ExtractionField("personal_use", "boolean", "Whether the vehicle is for personal use", required=True),
        ],
        "GET_MODIFIED": [
            ExtractionField("modified", "boolean", "Whether the vehicle is materially modified", required=True),
        ],
        "GET_ISSUES": [
            ExtractionField("issues_now", "boolean", "Whether the vehicle has active issues or warning lights", required=True),
        ],
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = deepcopy(config or DEFAULT_CONFIG)

    def get_opening_message(self, context: WorkflowContext) -> str:
        return (
            "Vehicle Service Department, this is Kay in activations. "
            "I'm calling about the coverage notice that was recently mailed out. "
            "To get started, what's your letter reference number?"
        )

    def derive_state_from_facts(self, facts: Dict[str, Any]) -> str:
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

    def next_question_for_state(self, state: str, facts: Dict[str, Any], context: WorkflowContext) -> str:
        if state == "GET_REFERENCE_ID":
            return self.get_opening_message(context)
        if state == "GET_NAME_CONFIRMATION":
            return f"Thanks. I have this registration under {context.caller_name}. Can you confirm your name? (yes/no)"
        if state == "GET_VEHICLE":
            return "Thanks. What's the year, make, and model of the vehicle?"
        if state == "GET_MILEAGE":
            return "About how many miles are on it? An estimate is fine."
        if state == "GET_DECISION_MAKER":
            return "Just to confirm - are you the decision maker for the vehicle? (yes/no)"
        if state == "GET_PERSONAL_USE":
            return "Just to confirm - is it for personal use (not business/fleet)? (yes/no)"
        if state == "GET_MODIFIED":
            return "Just to confirm - is it modified in any major way? (yes/no)"
        if state == "GET_ISSUES":
            return "Just to confirm - are there any mechanical issues or warning lights right now? (yes/no)"
        return "Thanks - you're all set. I'm going to connect you to an agent now."

    def detect_deviation(self, user_msg: str, facts: Dict[str, Any]) -> Dict[str, bool]:
        sample = (user_msg or "").lower()
        asked_pricing = any(token in sample for token in ["price", "cost", "how much", "$", "payment"])
        asked_coverage = any(token in sample for token in ["cover", "coverage", "what does it", "what is included"])
        trust_scam = any(token in sample for token in ["scam", "fraud", "legit", "legitimate", "spam", "how did you get"])
        already_have_policy = any(token in sample for token in ["already have", "i'm paying", "i paid", "another company", "cancel", "refund", "charge"])
        diagnostic = any(token in sample for token in ["check engine", "leak", "leaking", "transmission", "warning", "service message", "broke down", "screen went"])
        confused = any(token in sample for token in ["who are you", "where did you get", "i don't understand", "what is this", "not sure what this is"])
        not_dm = any(token in sample for token in ["not the decision", "my husband", "my wife", "he's not here", "she's not here", "need to ask", "i'll ask him", "i'll ask her"])
        return {
            "asked_pricing": asked_pricing,
            "asked_coverage_details": asked_coverage,
            "trust_or_scam": trust_scam,
            "already_have_policy": already_have_policy,
            "diagnostic_discussion": diagnostic,
            "confused": confused,
            "not_decision_maker": not_dm or (facts.get("decision_maker") is False),
        }

    def validate_year(self, year: Optional[int]) -> Optional[int]:
        if year is None:
            return None
        if 1980 <= year <= CURRENT_YEAR + 1:
            return year
        return None

    def validate_mileage(self, mileage: Optional[int]) -> Optional[int]:
        if mileage is None:
            return None
        if 0 <= mileage <= 500000:
            return mileage
        return None

    def apply_rules(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        qcfg = self.config["qualification"]
        eligible = True
        reason_codes: List[str] = []

        year = facts.get("vehicle_year")
        mileage = facts.get("mileage")
        min_year = qcfg.get("min_vehicle_year")

        if year is not None and min_year is not None:
            if year < int(min_year):
                eligible = False
                reason_codes.append("year_below_minimum")
        elif year is not None:
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

    def handoff_result(
        self,
        facts: Dict[str, Any],
        state: str,
        answer: str,
        extraction: Any,
        turns_without_progress: int,
        save_attempt_used: bool,
        reason_codes: List[str],
        qualification: Optional[Dict[str, Any]] = None,
    ) -> TurnResult:
        return TurnResult(
            state=state,
            facts=facts,
            answer=answer,
            handoff=True,
            reason_codes=reason_codes,
            qualification=qualification,
            turns_without_progress=turns_without_progress,
            save_attempt_used=save_attempt_used,
            extraction=extraction,
        )

    def continue_result(
        self,
        facts: Dict[str, Any],
        state: str,
        answer: str,
        extraction: Any,
        turns_without_progress: int,
        save_attempt_used: bool,
    ) -> TurnResult:
        return TurnResult(
            state=state,
            facts=facts,
            answer=answer,
            handoff=False,
            turns_without_progress=turns_without_progress,
            save_attempt_used=save_attempt_used,
            extraction=extraction,
        )

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
        updated_facts = dict(facts)
        extraction = extractor.extract(self, state, user_msg, updated_facts, context)
        deviation = self.detect_deviation(user_msg, updated_facts)

        if any(
            [
                deviation["asked_pricing"],
                deviation["asked_coverage_details"],
                deviation["trust_or_scam"],
                deviation["already_have_policy"],
                deviation["diagnostic_discussion"],
                deviation["confused"],
            ]
        ):
            if self.config["deviation"]["allow_one_save_attempt"] and not save_attempt_used:
                answer = (
                    "I can help with that - first I just need to confirm a few details from the notice so I can get you to the right person. "
                    "What's your letter reference number?"
                )
                return self.continue_result(
                    updated_facts,
                    state,
                    answer,
                    extraction,
                    turns_without_progress + 1,
                    True,
                )

            return self.handoff_result(
                updated_facts,
                "HANDOFF",
                "No problem - I'm going to connect you to an agent now.",
                extraction,
                turns_without_progress,
                True,
                ["deviation_topic"],
                qualification=None,
            )

        if state == "GET_REFERENCE_ID":
            reference_id = extraction.data.get("reference_id")
            if reference_id:
                updated_facts["reference_id"] = reference_id
                new_state = "GET_NAME_CONFIRMATION"
                return self.continue_result(
                    updated_facts,
                    new_state,
                    self.next_question_for_state(new_state, updated_facts, context),
                    extraction,
                    0,
                    save_attempt_used,
                )

            turns_without_progress += 1
            if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                return self.handoff_result(
                    updated_facts,
                    "HANDOFF",
                    "No problem - I'm going to connect you to an agent now.",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                    ["unclear_reference_id"],
                    qualification=None,
                )

            return self.continue_result(
                updated_facts,
                state,
                "Sorry - I didn't catch that. What's the letter reference number?",
                extraction,
                turns_without_progress,
                save_attempt_used,
            )

        if state == "GET_NAME_CONFIRMATION":
            confirmed = extraction.data.get("name_confirmed")
            if confirmed is not None:
                updated_facts["name_confirmed"] = confirmed
                if confirmed is True:
                    new_state = "GET_VEHICLE"
                    return self.continue_result(
                        updated_facts,
                        new_state,
                        self.next_question_for_state(new_state, updated_facts, context),
                        extraction,
                        0,
                        save_attempt_used,
                    )
                return self.handoff_result(
                    updated_facts,
                    "HANDOFF",
                    "No problem - I'm going to connect you to an agent now.",
                    extraction,
                    0,
                    save_attempt_used,
                    ["name_not_confirmed"],
                    qualification=None,
                )

            turns_without_progress += 1
            if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                return self.handoff_result(
                    updated_facts,
                    "HANDOFF",
                    "No problem - I'm going to connect you to an agent now.",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                    ["unclear_name_confirmation"],
                    qualification=None,
                )
            return self.continue_result(
                updated_facts,
                state,
                f"Sorry - I just need a yes or no. Is your name {context.caller_name}? (yes/no)",
                extraction,
                turns_without_progress,
                save_attempt_used,
            )

        if state == "GET_VEHICLE":
            year = self.validate_year(extraction.data.get("vehicle_year"))
            make = extraction.data.get("vehicle_make")
            model = extraction.data.get("vehicle_model")

            if year is not None:
                updated_facts["vehicle_year"] = year
            if make:
                updated_facts["vehicle_make"] = make
            if model:
                updated_facts["vehicle_model"] = model

            if updated_facts.get("vehicle_year") is None or updated_facts.get("vehicle_make") is None or updated_facts.get("vehicle_model") is None:
                turns_without_progress += 1
                if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                    return self.handoff_result(
                        updated_facts,
                        "HANDOFF",
                        "No problem - I'm going to connect you to an agent now.",
                        extraction,
                        turns_without_progress,
                        save_attempt_used,
                        ["missing_vehicle_info"],
                        qualification=None,
                    )
                return self.continue_result(
                    updated_facts,
                    state,
                    "Sorry - I just need the year, make, and model (example: 2021 Ford Fiesta). What's the year, make, and model?",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                )

            decision = self.apply_rules(updated_facts)
            if not decision["eligible"] and "year_below_minimum" in decision["reason_codes"]:
                return self.handoff_result(
                    updated_facts,
                    "HANDOFF",
                    "Thanks - based on the vehicle year, it looks like this vehicle doesn't meet the eligibility criteria. I'm going to connect you to an agent to go over options.",
                    extraction,
                    0,
                    save_attempt_used,
                    ["not_eligible"] + decision["reason_codes"],
                    qualification=decision,
                )

            new_state = "GET_MILEAGE"
            return self.continue_result(
                updated_facts,
                new_state,
                self.next_question_for_state(new_state, updated_facts, context),
                extraction,
                0,
                save_attempt_used,
            )

        if state == "GET_MILEAGE":
            mileage = self.validate_mileage(extraction.data.get("mileage"))
            if mileage is None:
                turns_without_progress += 1
                if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                    return self.handoff_result(
                        updated_facts,
                        "HANDOFF",
                        "No problem - I'm going to connect you to an agent now.",
                        extraction,
                        turns_without_progress,
                        save_attempt_used,
                        ["unclear_mileage"],
                        qualification=None,
                    )
                return self.continue_result(
                    updated_facts,
                    state,
                    "Sorry - about how many miles are on it? You can reply like \"42000\" or \"42k\".",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                )

            updated_facts["mileage"] = mileage
            decision = self.apply_rules(updated_facts)
            if not decision["eligible"] and "mileage_above_maximum" in decision["reason_codes"]:
                return self.handoff_result(
                    updated_facts,
                    "HANDOFF",
                    "Thanks - based on the mileage, it looks like this vehicle doesn't meet the eligibility criteria. I'm going to connect you to an agent to go over options.",
                    extraction,
                    0,
                    save_attempt_used,
                    ["not_eligible"] + decision["reason_codes"],
                    qualification=decision,
                )

            new_state = "GET_DECISION_MAKER"
            return self.continue_result(
                updated_facts,
                new_state,
                self.next_question_for_state(new_state, updated_facts, context),
                extraction,
                0,
                save_attempt_used,
            )

        if state == "GET_DECISION_MAKER":
            value = extraction.data.get("decision_maker")
            if value is None:
                turns_without_progress += 1
                if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                    return self.handoff_result(
                        updated_facts,
                        "HANDOFF",
                        "No problem - I'm going to connect you to an agent now.",
                        extraction,
                        turns_without_progress,
                        save_attempt_used,
                        ["unclear_decision_maker"],
                        qualification=None,
                    )
                return self.continue_result(
                    updated_facts,
                    state,
                    "Sorry - just yes or no: are you the decision maker for the vehicle? (yes/no)",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                )
            updated_facts["decision_maker"] = value
            new_state = "GET_PERSONAL_USE"
            return self.continue_result(
                updated_facts,
                new_state,
                self.next_question_for_state(new_state, updated_facts, context),
                extraction,
                0,
                save_attempt_used,
            )

        if state == "GET_PERSONAL_USE":
            value = extraction.data.get("personal_use")
            if value is None:
                turns_without_progress += 1
                if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                    return self.handoff_result(
                        updated_facts,
                        "HANDOFF",
                        "No problem - I'm going to connect you to an agent now.",
                        extraction,
                        turns_without_progress,
                        save_attempt_used,
                        ["unclear_personal_use"],
                        qualification=None,
                    )
                return self.continue_result(
                    updated_facts,
                    state,
                    "Sorry - just yes or no: is it for personal use (not business/fleet)? (yes/no)",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                )
            updated_facts["personal_use"] = value
            new_state = "GET_MODIFIED"
            return self.continue_result(
                updated_facts,
                new_state,
                self.next_question_for_state(new_state, updated_facts, context),
                extraction,
                0,
                save_attempt_used,
            )

        if state == "GET_MODIFIED":
            value = extraction.data.get("modified")
            if value is None:
                turns_without_progress += 1
                if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                    return self.handoff_result(
                        updated_facts,
                        "HANDOFF",
                        "No problem - I'm going to connect you to an agent now.",
                        extraction,
                        turns_without_progress,
                        save_attempt_used,
                        ["unclear_modified"],
                        qualification=None,
                    )
                return self.continue_result(
                    updated_facts,
                    state,
                    "Sorry - just yes or no: is it modified in any major way? (yes/no)",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                )
            updated_facts["modified"] = value
            new_state = "GET_ISSUES"
            return self.continue_result(
                updated_facts,
                new_state,
                self.next_question_for_state(new_state, updated_facts, context),
                extraction,
                0,
                save_attempt_used,
            )

        if state == "GET_ISSUES":
            value = extraction.data.get("issues_now")
            if value is None:
                turns_without_progress += 1
                if turns_without_progress >= self.config["deviation"]["max_turns_without_progress"]:
                    return self.handoff_result(
                        updated_facts,
                        "HANDOFF",
                        "No problem - I'm going to connect you to an agent now.",
                        extraction,
                        turns_without_progress,
                        save_attempt_used,
                        ["unclear_issues_now"],
                        qualification=None,
                    )
                return self.continue_result(
                    updated_facts,
                    state,
                    "Sorry - just yes or no: any mechanical issues or warning lights right now? (yes/no)",
                    extraction,
                    turns_without_progress,
                    save_attempt_used,
                )

            updated_facts["issues_now"] = value
            decision = self.apply_rules(updated_facts)
            reason_codes = ["qualified"] if decision["eligible"] else ["not_eligible"] + decision["reason_codes"]
            return self.handoff_result(
                updated_facts,
                "HANDOFF",
                "Thanks - you're all set. I'm going to connect you to an agent now.",
                extraction,
                0,
                save_attempt_used,
                reason_codes,
                qualification=decision,
            )

        new_state = self.derive_state_from_facts(updated_facts)
        return self.continue_result(
            updated_facts,
            new_state,
            self.next_question_for_state(new_state, updated_facts, context),
            extraction,
            turns_without_progress,
            save_attempt_used,
        )
