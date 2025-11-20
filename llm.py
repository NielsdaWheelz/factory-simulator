"""
LLM Helper Module

Provides a single helper function, call_llm_json, which calls the OpenAI chat completion API
with JSON-mode response formatting and parses the result into a Pydantic model.

The OpenAI library is imported inside the function to avoid a hard dependency at import time,
allowing tests to monkeypatch this function without requiring the openai package.
"""

import json
import logging
from typing import Type, TypeVar

from pydantic import BaseModel

from config import get_openai_api_key, OPENAI_MODEL

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def call_llm_json(prompt: str, schema: Type[T]) -> T:
    """
    Call the OpenAI chat completion API with a prompt that is expected to
    return a single JSON object, and parse it into the given Pydantic schema.

    This function:
    - Reads OPENAI_API_KEY using config.get_openai_api_key()
    - Uses OPENAI_MODEL from config
    - Uses response_format={"type": "json_object"} to force JSON mode
    - Parses the JSON into the provided Pydantic model
    - Raises RuntimeError with a clear message on failure.

    Args:
        prompt: The full prompt to send to the LLM.
        schema: A Pydantic BaseModel class to validate and parse the response into.

    Returns:
        An instance of the provided schema, populated from the LLM response.

    Raises:
        RuntimeError: If the openai package is not installed, or if LLM call fails.

    NOTE:
    - This function will ONLY be called in non-test code paths.
    - Tests will monkeypatch this function to avoid real network calls.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is not installed. Install it to use LLM-backed agents."
        ) from exc

    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)

    logger.info("calling LLM for schema %s", schema.__name__)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise JSON-emitting assistant."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM response was empty")

        data = json.loads(content)
        parsed = schema.model_validate(data)

        return parsed
    except Exception:
        logger.exception("LLM call failed")
        raise
