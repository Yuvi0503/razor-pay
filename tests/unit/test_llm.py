import json

from backend.domain.enums import ActionType, ReasonCode
from backend.llm.advisor import LLMAdvisor
from backend.llm.cache import SQLiteResponseCache


def valid(action: ActionType = ActionType.CREATE_PAYMENT_LINK) -> str:
    return json.dumps(
        {
            "action": action.value,
            "delay_minutes": 30,
            "confidence": 0.6,
            "reason_codes": [ReasonCode.CUSTOMER_CONTEXT.value],
            "rationale": "Use the eligible recovery path.",
        }
    )


def test_llm_is_optional_and_defaults_to_rule_fallback() -> None:
    advisor = LLMAdvisor()
    result = advisor.decide({}, (ActionType.CREATE_PAYMENT_LINK,), ActionType.CREATE_PAYMENT_LINK)
    assert result.source == "RULE"
    assert result.fallback_reason == "LLM_UNAVAILABLE"
    assert result.decision.action is ActionType.CREATE_PAYMENT_LINK


def test_ineligible_action_is_rejected_and_falls_back() -> None:
    advisor = LLMAdvisor(lambda _prompt, _timeout: valid(ActionType.RETRY_MANDATE_CHARGE))
    result = advisor.decide({}, (ActionType.CREATE_PAYMENT_LINK,), ActionType.CREATE_PAYMENT_LINK)
    assert result.source == "RULE"
    assert result.fallback_reason == "LLM_INELIGIBLE_ACTION"
    assert advisor.stats.ineligible_actions == 1


def test_malformed_json_gets_one_retry_then_fallback() -> None:
    advisor = LLMAdvisor(lambda _prompt, _timeout: "not-json")
    result = advisor.decide({}, (ActionType.CREATE_PAYMENT_LINK,), ActionType.CREATE_PAYMENT_LINK)
    assert result.source == "RULE"
    assert result.fallback_reason == "LLM_SCHEMA_INVALID"
    assert advisor.stats.schema_failures == 2


def test_cache_key_reuses_valid_response(tmp_path) -> None:
    calls = 0

    def provider(_prompt: str, _timeout: float) -> str:
        nonlocal calls
        calls += 1
        return valid()

    cache = SQLiteResponseCache(str(tmp_path / "llm.sqlite"))
    advisor = LLMAdvisor(provider, cache=cache)
    first = advisor.decide({"case": "same"}, (ActionType.CREATE_PAYMENT_LINK,), ActionType.CREATE_PAYMENT_LINK)
    second = advisor.decide({"case": "same"}, (ActionType.CREATE_PAYMENT_LINK,), ActionType.CREATE_PAYMENT_LINK)
    assert first.decision == second.decision
    assert calls == 1
    assert advisor.stats.cache_hits == 1
    cache.close()
