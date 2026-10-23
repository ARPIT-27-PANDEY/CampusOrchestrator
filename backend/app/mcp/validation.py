"""JSON-Schema validation of model-generated tool arguments (before anything reaches a server)."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

_FORMAT_CHECKER = FormatChecker()


def validate_arguments(schema: dict[str, Any], arguments: Any) -> list[str]:
    """Return human-readable validation errors (empty list means valid)."""
    if not isinstance(arguments, dict):
        return ["Tool arguments must be a JSON object."]
    try:
        validator = Draft202012Validator(schema, format_checker=_FORMAT_CHECKER)
    except SchemaError:  # pragma: no cover - server published an invalid schema
        return ["Server published an invalid input schema for this tool."]
    errors = []
    for err in sorted(validator.iter_errors(arguments), key=lambda e: list(e.path)):
        location = ".".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{location}: {err.message}")
    return errors[:10]
