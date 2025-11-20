#!/usr/bin/env python3
"""
Direct debug script to test OnboardingAgent with instrumentation.

This will:
1. Monkey-patch call_llm_json to log the raw LLM response
2. Call OnboardingAgent.run() directly with the 3m/4j test factory
3. Show what the agent actually returns before orchestration
"""

import sys
import os
import json
import logging
from unittest.mock import patch

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Test factory text (exact from bug report)
factory_text = """We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h).
"""

# Import after setup
from backend.agents import OnboardingAgent
from backend.models import FactoryConfig
from backend.llm import call_llm_json


def mock_call_llm_json(prompt: str, schema):
    """
    Mock LLM call that logs the raw response and response structure.

    This calls the REAL LLM but captures and logs the response.
    """
    from openai import OpenAI
    from backend.config import get_openai_api_key, OPENAI_MODEL

    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)

    logger.info("=" * 80)
    logger.info("CALLING REAL LLM")
    logger.info("=" * 80)
    logger.info(f"Model: {OPENAI_MODEL}")
    logger.info(f"Schema: {schema.__name__}")
    logger.info(f"Prompt length: {len(prompt)} chars")
    logger.info(f"Prompt preview (first 500 chars):\n{prompt[:500]}")

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

        logger.info("=" * 80)
        logger.info("RAW LLM RESPONSE:")
        logger.info("=" * 80)
        logger.info(f"Content length: {len(content) if content else 0} chars")
        if content:
            logger.info(f"Content:\n{content}")
            # Try to parse and pretty-print
            try:
                data = json.loads(content)
                logger.info(f"Parsed JSON (pretty):\n{json.dumps(data, indent=2)}")
            except Exception as e:
                logger.error(f"Failed to parse JSON: {e}")
        else:
            logger.error("LLM response was empty (None)")

        if content is None:
            raise RuntimeError("LLM response was empty")

        data = json.loads(content)
        parsed = schema.model_validate(data)

        logger.info("=" * 80)
        logger.info("PARSED FACTORYCONFIG:")
        logger.info("=" * 80)
        logger.info(f"Machines: {len(parsed.machines)}")
        for m in parsed.machines:
            logger.info(f"  - {m.id}: {m.name}")
        logger.info(f"Jobs: {len(parsed.jobs)}")
        for j in parsed.jobs:
            logger.info(f"  - {j.id}: {j.name} ({len(j.steps)} steps)")

        return parsed
    except Exception as e:
        logger.exception(f"LLM call failed: {type(e).__name__}: {str(e)}")
        raise


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    print("=" * 80)
    print("DEBUG: OnboardingAgent Direct Call")
    print("=" * 80)
    print(f"\nFactory text:\n{factory_text}\n")

    # Patch call_llm_json with our instrumented version
    with patch('backend.agents.call_llm_json', side_effect=mock_call_llm_json):
        agent = OnboardingAgent()
        try:
            cfg = agent.run(factory_text)

            print("\n" + "=" * 80)
            print("AGENT RETURNED:")
            print("=" * 80)
            print(f"Machines: {len(cfg.machines)}")
            for m in cfg.machines:
                print(f"  - {m.id}: {m.name}")
            print(f"Jobs: {len(cfg.jobs)}")
            for j in cfg.jobs:
                print(f"  - {j.id}: {j.name} ({len(j.steps)} steps)")

            if len(cfg.machines) >= 3 and len(cfg.jobs) >= 4:
                print("\n✓ SUCCESS: Got 3m/4j as expected!")
            else:
                print(f"\n✗ FAILURE: Got {len(cfg.machines)}m/{len(cfg.jobs)}j instead of 3m/4j")
                sys.exit(1)
        except Exception as e:
            print(f"\n✗ Agent.run() threw exception: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
