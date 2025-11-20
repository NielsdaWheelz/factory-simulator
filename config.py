import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_MODEL = "gpt5nano"


def get_openai_api_key() -> str:
    """
    Return the OPENAI_API_KEY from environment.

    Raises:
        RuntimeError: if the env var is missing or empty.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set; please export it before running LLM-backed code."
        )
    return api_key
