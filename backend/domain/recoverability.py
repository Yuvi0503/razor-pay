from .enums import CaseClass, FailureCategory, Recoverability


def derive(case_class: CaseClass, category: FailureCategory) -> Recoverability:
    if category in {FailureCategory.CUSTOMER_CANCELLED, FailureCategory.MANDATE_INVALID}:
        return Recoverability.NOT_RECOVERABLE
    if case_class is CaseClass.A_MANDATE and category in {
        FailureCategory.TEMPORARY_GATEWAY_ERROR,
        FailureCategory.TEMPORARY_BANK_ERROR,
        FailureCategory.INSUFFICIENT_FUNDS,
    }:
        return Recoverability.AUTOMATED
    return Recoverability.ASSISTED
