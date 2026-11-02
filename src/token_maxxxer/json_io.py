"""Strict JSON decoding shared by CLI metadata, result validation and redaction."""

import json
from typing import NoReturn


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def load_unique_json(value: str) -> object:
    decoded: object = json.loads(
        value,
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_constant,
    )
    return decoded
