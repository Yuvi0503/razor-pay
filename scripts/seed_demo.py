"""Seed repeatable simulator-backed cases into the running demo database."""

from sqlalchemy import select

from backend.db.engine import get_session
from backend.db.models import Order, RecoveryCase
from backend.domain.enums import CaseClass, FailureCategory
from backend.gateway.base import GatewayAdapter
from backend.policy.config_loader import load
from eval.pipeline import run_scenario
from sim.gateway import SimulatedGateway
from sim.scenarios import Scenario

SCENARIOS = (
    Scenario(
        key="demo-oneoff",
        case_class=CaseClass.B_ONEOFF,
        failure_category=FailureCategory.INSUFFICIENT_FUNDS,
        amount_paise=149900,
        organic_probability=0.08,
        recovery_probability=0.45,
        notes="Customer requested an alternate payment method.",
        method="card",
        issuer_or_bank="demo-bank-a",
    ),
    Scenario(
        key="demo-mandate",
        case_class=CaseClass.A_MANDATE,
        failure_category=FailureCategory.TEMPORARY_BANK_ERROR,
        amount_paise=249900,
        organic_probability=0.06,
        recovery_probability=0.50,
        notes="Mandate-backed subscription charge failed temporarily.",
        method="upi",
        issuer_or_bank="demo-bank-b",
    ),
    Scenario(
        key="demo-high-value",
        case_class=CaseClass.B_ONEOFF,
        failure_category=FailureCategory.AUTHENTICATION_FAILED,
        amount_paise=1500000,
        organic_probability=0.04,
        recovery_probability=0.35,
        notes="High-value recovery requires explicit human approval.",
        method="card",
        issuer_or_bank="demo-bank-c",
    ),
)


def already_seeded(session, scenario: Scenario) -> bool:
    return session.scalar(
        select(RecoveryCase)
        .join(Order, RecoveryCase.order_id == Order.id)
        .where(Order.provider_order_id == f"order_{scenario.key}")
    ) is not None


def main() -> None:
    policy = load()
    gateway: GatewayAdapter = SimulatedGateway(seed=42)
    session = next(get_session())
    try:
        for scenario in SCENARIOS:
            if already_seeded(session, scenario):
                print(f"skipped {scenario.key}: already present")
                continue
            result = run_scenario(
                scenario,
                arm="rules",
                seed=42,
                policy=policy,
                gateway=gateway,  # type: ignore[arg-type]
                session=session,
                auto_approve=scenario.key != "demo-high-value",
            )
            session.commit()
            print(f"seeded {scenario.key}: state={result.state.value} case_id={result.case_id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
