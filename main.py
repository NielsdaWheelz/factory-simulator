"""
CLI Entrypoint Module

LLM-driven factory simulation CLI:
- Accepts free-text description of today's situation (via CLI args or interactive prompt)
- Calls run_pipeline(user_text) to orchestrate intent → scenarios → sim → metrics → briefing
- Prints decision briefing markdown to stdout

Usage:
    python -m main "describe today's situation..."
    python -m main  # interactive mode
"""

import argparse
import logging
from orchestrator import run_pipeline


def main() -> int:
    """Run the factory simulator CLI.

    Returns:
        0 on success, 1 on error or user abort.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="LLM-driven factory simulation demo (intent → scenarios → sim → metrics → briefing)."
    )
    parser.add_argument(
        "description",
        nargs="*",
        help="Free-text description of today's situation (rush orders, constraints, acceptable trade-offs).",
    )
    args = parser.parse_args()

    if args.description:
        user_text = " ".join(args.description)
    else:
        print("describe today's situation (rush orders, constraints, trade-offs), then press enter:")
        try:
            user_text = input("> ").strip()
        except KeyboardInterrupt:
            print("\naborted.")
            return 1

    if not user_text:
        print("no description provided; nothing to do.")
        return 1

    try:
        output = run_pipeline(user_text)
    except Exception as exc:  # noqa: BLE001
        logging.exception("pipeline crashed")
        print(f"\nERROR: {exc}")
        return 1

    briefing = output["briefing"]

    print("\n=== DECISION BRIEFING ===\n")
    print(briefing)
    print("\n=== END ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
