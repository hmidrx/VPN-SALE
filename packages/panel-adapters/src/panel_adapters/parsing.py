"""Typed parsing boundary for untrusted provider JSON payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from vpnsale_domain.providers import ProviderError, ProviderErrorCode

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | Mapping[str, object] | Sequence[object]
JsonMapping = Mapping[str, object]
JsonSequence = Sequence[object]


class ParseIssue(StrEnum):
    INVALID_MAPPING = "invalid_mapping"
    INVALID_LIST = "invalid_list"
    INVALID_STRING = "invalid_string"
    INVALID_INTEGER = "invalid_integer"
    INVALID_BOOLEAN = "invalid_boolean"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_JSON = "invalid_json"


def provider_parse_error(issue: ParseIssue, field: str) -> ProviderError:
    return ProviderError(ProviderErrorCode.PROVIDER_RESPONSE_INVALID, f"{issue.value}:{field}")


def require_mapping(value: object, field: str) -> JsonMapping:
    if isinstance(value, Mapping):
        return cast(JsonMapping, value)
    raise provider_parse_error(ParseIssue.INVALID_MAPPING, field)


def optional_mapping(value: object, field: str) -> JsonMapping | None:
    if value is None:
        return None
    return require_mapping(value, field)


def require_sequence(value: object, field: str) -> JsonSequence:
    if isinstance(value, str) or isinstance(value, bytes) or not isinstance(value, Sequence):
        raise provider_parse_error(ParseIssue.INVALID_LIST, field)
    return cast(JsonSequence, value)


def optional_sequence(value: object, field: str) -> JsonSequence | None:
    if value is None:
        return None
    return require_sequence(value, field)


def optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise provider_parse_error(ParseIssue.INVALID_STRING, field)


def require_string(value: object, field: str) -> str:
    parsed = optional_string(value, field)
    if parsed is None or parsed == "":
        raise provider_parse_error(ParseIssue.INVALID_STRING, field)
    return parsed


def optional_identifier(value: object, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise provider_parse_error(ParseIssue.INVALID_STRING, field)


def require_identifier(value: object, field: str) -> str:
    parsed = optional_identifier(value, field)
    if parsed is None:
        raise provider_parse_error(ParseIssue.INVALID_STRING, field)
    return parsed


def optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise provider_parse_error(ParseIssue.INVALID_INTEGER, field)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise provider_parse_error(ParseIssue.INVALID_INTEGER, field)


def optional_non_negative_int(value: object, field: str) -> int | None:
    parsed = optional_int(value, field)
    if parsed is not None and parsed < 0:
        raise provider_parse_error(ParseIssue.INVALID_INTEGER, field)
    return parsed


def optional_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return value == 1
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise provider_parse_error(ParseIssue.INVALID_BOOLEAN, field)


def optional_epoch_datetime(value: object, field: str) -> datetime | None:
    parsed = optional_int(value, field)
    if parsed is None or parsed == 0:
        return None
    seconds = parsed / 1000 if parsed > 10_000_000_000 else parsed
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise provider_parse_error(ParseIssue.INVALID_TIMESTAMP, field) from exc


def parse_json_mapping_string(value: object, field: str) -> JsonMapping | None:
    text = optional_string(value, field)
    if text is None or text == "":
        return None
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise provider_parse_error(ParseIssue.INVALID_JSON, field) from exc
    return require_mapping(decoded, field)


def first_present(mapping: JsonMapping, keys: Sequence[str]) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None
