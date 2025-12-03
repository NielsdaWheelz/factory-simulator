"""
LLM Helper Module

Provides a single helper function, call_llm_json, which calls the OpenAI chat completion API
with JSON-mode response formatting and parses the result into a Pydantic model.

The OpenAI library is imported inside the function to avoid a hard dependency at import time,
allowing tests to monkeypatch this function without requiring the openai package.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Type, TypeVar

from pydantic import BaseModel

from .config import get_openai_api_key, OPENAI_MODEL

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    """Result of an LLM call with metadata for observability."""
    data: BaseModel
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


def call_llm_json_with_metadata(prompt: str, schema: Type[T]) -> LLMResult:
    """
    Call the OpenAI chat completion API and return result with metadata.
    
    Returns LLMResult with the parsed data plus timing and token info.
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

    start_time = time.time()
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise JSON-emitting assistant."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.time() - start_time) * 1000)

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM response was empty")

        data = json.loads(content)
        parsed = schema.model_validate(data)

        # Extract token counts if available
        input_tokens = None
        output_tokens = None
        if response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

        return LLMResult(
            data=parsed,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except Exception:
        logger.exception("LLM call failed")
        raise


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
    result = call_llm_json_with_metadata(prompt, schema)
    return result.data  # type: ignore
