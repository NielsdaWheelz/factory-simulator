#!/usr/bin/env python3
"""
Dump the exact prompt being sent to the LLM to debug issues.
"""

from backend.agents import OnboardingAgent

factory_text = """We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h).
"""

agent = OnboardingAgent()
prompt = agent._build_prompt(factory_text)

# Write the full prompt to a file
with open("/tmp/prompt_sent_to_llm.txt", "w") as f:
    f.write(prompt)

print(f"Prompt written to /tmp/prompt_sent_to_llm.txt")
print(f"Prompt length: {len(prompt)} chars")

# Show key sections
print("\n" + "=" * 80)
print("KEY SECTIONS IN PROMPT:")
print("=" * 80)

if "CRITICAL RULE on fractional durations" in prompt:
    idx = prompt.find("CRITICAL RULE on fractional durations")
    print("\n✓ CRITICAL RULE found at position", idx)
    print(prompt[idx:idx+500])
else:
    print("\n✗ CRITICAL RULE NOT FOUND in prompt!")

if "EXAMPLE E:" in prompt:
    idx = prompt.find("EXAMPLE E:")
    print("\n✓ EXAMPLE E found at position", idx)
    print(prompt[idx:idx+600])
else:
    print("\n✗ EXAMPLE E NOT FOUND in prompt!")

if "J1, J2, J3, J4" in prompt:
    print("\n✓ J1, J2, J3, J4 reference found in prompt (from user input)")
else:
    print("\n✗ J1, J2, J3, J4 reference NOT in prompt (user input missing?)")

if "ROLE & GUARDRAILS" in prompt:
    idx = prompt.find("ROLE & GUARDRAILS")
    print("\n✓ ROLE & GUARDRAILS section found")
    print(prompt[idx:idx+700])
