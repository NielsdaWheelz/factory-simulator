"""
Agent Type Definitions

Core abstractions for the SOTA agent architecture:
- AgentState: The unified state object tracking everything about the current run
- AgentDecision: The structured output from the LLM (thought + action)
- Message: A single message in the conversation history
- ToolCall: A request to execute a specific tool
- ToolResult: The outcome of a tool execution
"""

from enum import Enum
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field

from .models import FactoryConfig, ScenarioSpec, ScenarioMetrics


# =============================================================================
# ENUMS
# =============================================================================

class AgentStatus(str, Enum):
    """Current status of the agent run."""
    RUNNING = "RUNNING"      # Agent is still working
    DONE = "DONE"            # Agent completed successfully
    FAILED = "FAILED"        # Agent hit an unrecoverable error
    MAX_STEPS = "MAX_STEPS"  # Agent hit step limit


# =============================================================================
# MESSAGE TYPES (Conversation History)
# =============================================================================

class Message(BaseModel):
    """A single message in the agent's conversation history."""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_call_id: Optional[str] = None  # Links tool result to tool call
    name: Optional[str] = None          # Tool name for tool messages


# =============================================================================
# TOOL CALL TYPES
# =============================================================================

class ToolCall(BaseModel):
    """
    Represents the LLM's decision to call a specific tool.
    
    The LLM outputs this structure to indicate which tool to run
    and with what arguments.
    """
    id: str = Field(..., description="Unique ID for this tool call (for tracking)")
    name: str = Field(..., description="Name of the tool to call")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")


class ToolResult(BaseModel):
    """
    The outcome of executing a tool.
    
    This gets fed back into the agent's observation on the next loop iteration.
    """
    tool_call_id: str = Field(..., description="Links back to the ToolCall.id")
    tool_name: str
    success: bool
    output: Any = None          # The actual result (FactoryConfig, Metrics, etc.)
    error: Optional[str] = None # Error message if success=False


# =============================================================================
# AGENT DECISION (LLM Output Schema)
# =============================================================================

class AgentDecision(BaseModel):
    """
    The structured output from the LLM at each step.
    
    This enforces that the LLM must:
    1. Think (explain reasoning)
    2. Decide (tool_call or final_answer)
    
    The schema prevents free-form rambling and ensures actionable output.
    """
    thought: str = Field(
        ..., 
        description="Internal reasoning: What do I know? What should I do next? Why?"
    )
    action_type: Literal["tool_call", "final_answer"] = Field(
        ...,
        description="Either call a tool or provide the final answer to the user"
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="Tools to execute (only if action_type='tool_call')"
    )
    final_answer: Optional[str] = Field(
        default=None, 
        description="The final response to the user (only if action_type='final_answer')"
    )


# =============================================================================
# AGENT STATE (The Source of Truth)
# =============================================================================

class AgentState(BaseModel):
    """
    The Source of Truth for the Agent.
    
    This object tracks EVERYTHING about the current run:
    - What the user asked
    - What messages have been exchanged
    - What the agent has learned (factory config, simulation results)
    - Where we are in the execution (step count, status)
    - Error tracking for retry logic
    
    This is the "brain" that persists across loop iterations.
    """
    
    # =========================================================================
    # INPUTS (Immutable after initialization)
    # =========================================================================
    user_request: str = Field(..., description="The original user query")
    
    # =========================================================================
    # CONFIGURATION (Tunable parameters)
    # =========================================================================
    max_steps: int = Field(default=15, description="Maximum loop iterations before giving up")
    max_consecutive_errors: int = Field(default=3, description="Max errors before failing")
    
    # =========================================================================
    # EXECUTION STATE (Mutable, updated each loop)
    # =========================================================================
    status: AgentStatus = Field(default=AgentStatus.RUNNING)
    steps: int = Field(default=0, description="Current step count")
    consecutive_errors: int = Field(default=0, description="Errors in a row (resets on success)")
    
    # Per-tool failure tracking
    tool_failure_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Consecutive failure count per tool name"
    )
    blocked_tools: set[str] = Field(
        default_factory=set,
        description="Tools blocked due to repeated failures (3+ consecutive)"
    )
    
    # =========================================================================
    # CONVERSATION HISTORY (The "Short-Term Memory")
    # =========================================================================
    messages: list[Message] = Field(
        default_factory=list,
        description="Full conversation history (system, user, assistant, tool messages)"
    )
    
    # =========================================================================
    # DOMAIN STATE (The "World" - What the agent has learned)
    # =========================================================================
    factory: Optional[FactoryConfig] = Field(
        default=None, 
        description="Parsed factory config (None until successfully extracted)"
    )
    factory_text: Optional[str] = Field(
        default=None,
        description="Raw factory description text (for re-parsing attempts)"
    )
    scenarios_run: list[ScenarioSpec] = Field(
        default_factory=list,
        description="Scenarios that have been simulated"
    )
    metrics_collected: list[ScenarioMetrics] = Field(
        default_factory=list,
        description="Metrics from each simulation run"
    )
    
    # =========================================================================
    # SCRATCHPAD (Agent's internal notes)
    # =========================================================================
    scratchpad: list[str] = Field(
        default_factory=list,
        description="Agent's internal reasoning trace (for debugging/observability)"
    )
    
    # =========================================================================
    # FINAL OUTPUT
    # =========================================================================
    final_answer: Optional[str] = Field(
        default=None,
        description="The final response to return to the user"
    )
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def add_message(self, role: str, content: str, **kwargs) -> None:
        """Append a message to conversation history."""
        self.messages.append(Message(role=role, content=content, **kwargs))
    
    def add_thought(self, thought: str) -> None:
        """Record a thought in the scratchpad."""
        self.scratchpad.append(f"[Step {self.steps}] {thought}")
    
    def increment_step(self) -> None:
        """Advance the step counter and check limits."""
        self.steps += 1
        if self.steps >= self.max_steps:
            self.status = AgentStatus.MAX_STEPS
    
    def record_error(self, error: str) -> None:
        """Track consecutive errors for retry logic."""
        self.consecutive_errors += 1
        self.add_thought(f"ERROR: {error}")
        if self.consecutive_errors >= self.max_consecutive_errors:
            self.status = AgentStatus.FAILED
            self.final_answer = f"I encountered too many consecutive errors and couldn't complete the task. Last error: {error}"
    
    def record_success(self, tool_name: str | None = None) -> None:
        """Reset error counter on successful tool execution."""
        self.consecutive_errors = 0
        if tool_name:
            self.tool_failure_counts[tool_name] = 0
    
    def record_tool_failure(self, tool_name: str, error: str, max_failures: int = 3) -> bool:
        """
        Track per-tool failures. Returns True if tool is now blocked.
        
        After max_failures consecutive failures for a specific tool,
        the tool is blocked for the rest of this session.
        """
        count = self.tool_failure_counts.get(tool_name, 0) + 1
        self.tool_failure_counts[tool_name] = count
        
        if count >= max_failures and tool_name not in self.blocked_tools:
            self.blocked_tools.add(tool_name)
            self.add_thought(f"BLOCKED: Tool '{tool_name}' failed {count} times. Giving up on it.")
            return True
        return False
    
    def is_tool_blocked(self, tool_name: str) -> bool:
        """Check if a tool is blocked due to repeated failures."""
        return tool_name in self.blocked_tools
    
    def complete(self, answer: str) -> None:
        """Mark the agent as done with a final answer."""
        self.status = AgentStatus.DONE
        self.final_answer = answer
    
    def is_running(self) -> bool:
        """Check if the agent should continue looping."""
        return self.status == AgentStatus.RUNNING

