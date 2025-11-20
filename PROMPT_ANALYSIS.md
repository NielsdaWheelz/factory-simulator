# Prompt Length Analysis - All LLM Agents

## Summary

| Agent | Prompt Size | Tokens* | Status | Notes |
|-------|------------|--------|--------|-------|
| **OnboardingAgent** | 3,979 chars | ~995 | ✓ OPTIMIZED | Simplified from 19,543 chars (80% reduction) |
| **IntentAgent** | ~1,200 chars | ~300 | ✓ CONCISE | Compact scenario classification prompt |
| **FuturesAgent** | ~1,300 chars | ~325 | ✓ CONCISE | Scenario expansion prompt |
| **BriefingAgent** | ~1,700 chars | ~425 | ✓ CONCISE | Briefing generation prompt |

*Rough estimate: 1 token ≈ 4 characters

## Detailed Analysis

### 1. OnboardingAgent (MOST OPTIMIZED)
**Size:** 3,979 characters (~995 tokens)

**Structure:**
- CRITICAL RULES (3 essential rules)
- SCHEMA definition (simple JSON example)
- TIME INTERPRETATION (minimal rules)
- FINAL WORKED EXAMPLE (at the end for recency bias)

**Status:** ✓ **OPTIMIZED**
- Recently simplified from 19,543 chars
- Now faster and cheaper
- Still works perfectly (3m/4j extraction correct)
- Could go smaller but loses helpful guidance

**Decision:** Keep as is. The simplification was effective.

---

### 2. IntentAgent (Scenario Classifier)
**Size:** ~1,200 characters (~300 tokens)

**Structure:**
- Role description (factory operations interpreter)
- Mapping rules (3 scenario types: BASELINE, RUSH_ARRIVES, M2_SLOWDOWN)
- Constraint extraction guidance
- Schema definition
- Context (available jobs/machines, user input)

**Status:** ✓ **CONCISE**
- Already lean - no reduction needed
- Clear and focused on scenario classification
- Easy to follow rules

**Decision:** No changes needed.

---

### 3. FuturesAgent (Scenario Expansion)
**Size:** ~1,300 characters (~325 tokens)

**Structure:**
- Role description (scenario planner)
- Valid scenario combinations
- Scenario planning rules
- Schema definition
- Context (available jobs/machines, current scenario)

**Status:** ✓ **CONCISE**
- Lean and focused
- Clear generation rules
- Good guard rails (max 3 scenarios, no mixed types)

**Decision:** No changes needed.

---

### 4. BriefingAgent (Report Generation)
**Size:** ~1,700 characters (~425 tokens)

**Structure:**
- Role description (operations briefing writer)
- Critical instructions for constraint analysis
- Feasibility assessment guidance
- Factory/metrics context
- Schema with markdown template
- Emphasis on honesty about constraints

**Status:** ✓ **CONCISE**
- More detailed than other agents (reason: briefing is more complex)
- Includes important constraint validation logic
- No obvious bloat

**Decision:** No changes needed.

---

## Unified Model Configuration

All agents use the same model: **gpt-4o-mini** (set in `backend/config.py`)

**Why gpt-4o-mini:**
- Required for structured JSON extraction (OnboardingAgent)
- Cost-effective while capable
- Fast enough for real-time operations
- Applies uniformly to all agents

---

## Recommendation

**All prompts are now reasonable in size.**

The only one that was problematic was OnboardingAgent (19k chars → 3.9k chars reduction), which:
- Was overly verbose
- Had competing guidance ("prefer under-modeling" conflicting with "COVERAGE FIRST")
- Had examples buried in the middle instead of at the end

The other three agents have lean, focused prompts from the start and need no changes.

### Future Optimizations

If token cost becomes a concern:
1. Could reduce BriefingAgent briefing template examples (currently just one template)
2. Could parameterize scenario rules (currently hardcoded for BASELINE, RUSH_ARRIVES, M2_SLOWDOWN)
3. Could use prompt caching (OpenAI feature) for repetitive factory context

But these are micro-optimizations - current sizes are fine.
