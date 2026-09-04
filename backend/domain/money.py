"""Runtime validation for integer paise money values."""


def require_paise(value: object, field_name: str = "amount_paise") -> int:
    """Require a non-negative integer number of paise."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer number of paise")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


__all__ = ["require_paise"]
