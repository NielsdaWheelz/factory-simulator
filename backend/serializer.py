"""
Serialization utilities for making pipeline outputs JSON-friendly.

Converts Pydantic models and enums to plain dicts and native Python types.
"""

from enum import Enum
from pydantic import BaseModel


def serialize_simulation_result(result: dict) -> dict:
    """
    Convert run_onboarded_pipeline output to JSON-serializable format.

    Handles:
    - Pydantic models (converts to dicts via .model_dump())
    - Enum values (converts to string via .value)
    - Nested structures (lists, dicts with the above)

    Args:
        result: Dict returned by run_onboarded_pipeline containing:
            - factory: FactoryConfig (Pydantic model)
            - specs: list[ScenarioSpec] (Pydantic models)
            - metrics: list[ScenarioMetrics] (Pydantic models)
            - briefing: str
            - meta: dict with onboarding metadata

    Returns:
        A new dict with all Pydantic models and enums converted to JSON-native types.
        Structure and field names are preserved.
    """
    serialized = {}

    for key, value in result.items():
        serialized[key] = _serialize_value(value)

    return serialized


def _serialize_value(value):
    """
    Recursively serialize a single value.

    Handles:
    - Pydantic BaseModel instances → dict
    - Enum instances → string value
    - Lists → list of serialized items
    - Dicts → dict of serialized key-value pairs
    - Primitives (str, int, float, bool, None) → pass through

    Args:
        value: The value to serialize

    Returns:
        JSON-serializable version of value
    """
    # Handle Pydantic models
    if isinstance(value, BaseModel):
        # Convert Pydantic model to dict, then recursively serialize the dict
        return _serialize_value(value.model_dump())

    # Handle enums
    if isinstance(value, Enum):
        return value.value

    # Handle lists
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]

    # Handle dicts
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}

    # Handle primitives (str, int, float, bool, None)
    return value
