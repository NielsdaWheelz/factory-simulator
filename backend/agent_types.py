"""
Agent Type Definitions

Core abstractions for the SOTA agent architecture:
- AgentState: The unified state object tracking everything about the current run
- AgentDecision: The structured output from the LLM (thought + action)
- PlanStep: A single step in the agent's execution plan
- ErrorInfo: Structured error information for typed error handling
- Message: A single message in the conversation history
- ToolCall: A request to execute a specific tool
- ToolResult: The outcome of a tool execution
"""

from enum import Enum
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field, PrivateAttr

from .models import FactoryConfig, ScenarioSpec, ScenarioMetrics


# =============================================================================
# ENUMS
# =============================================================================

class AgentStatus(str, Enum):
    """Current status of the agent run."""
    RUNNING = "RUNNING"              # Agent is still working
    DONE = "DONE"                    # Agent completed successfully
    FAILED = "FAILED"                # Agent hit an unrecoverable error
    MAX_STEPS = "MAX_STEPS"          # Agent hit step limit
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"  # LLM call budget exceeded
    DIAGNOSTIC_PENDING = "DIAGNOSTIC_PENDING"  # Needs diagnostic step


class PlanStepType(str, Enum):
    """Types of steps the agent can plan."""
    ENSURE_FACTORY = "ensure_factory"      # Parse or load factory
    SIMULATE_BASELINE = "simulate_baseline"  # Run baseline simulation
    SIMULATE_RUSH = "simulate_rush"        # Run rush order scenario
    SIMULATE_SLOWDOWN = "simulate_slowdown"  # Run machine slowdown scenario
    GENERATE_BRIEFING = "generate_briefing"  # Generate final report
    DIAGNOSTIC = "diagnostic"              # Error recovery / explanation


class ErrorType(str, Enum):
    """Explicit error taxonomy for different failure modes."""
    TOOL_TRANSIENT = "tool_transient"      # Timeouts, 5xx, rate limits
    TOOL_FATAL = "tool_fatal"              # Invalid scenario, bad args, impossible factory
    MODEL_SCHEMA = "model_schema"          # Invalid JSON, schema mismatch
    MODEL_POLICY = "model_policy"          # Unsafe output, disallowed action
    TASK_UNSAT = "task_unsatisfiable"      # We proved it's impossible (e.g., can't parse factory)


class OnboardingIssueSeverity(str, Enum):
    """Severity levels for onboarding issues."""
    INFO = "info"          # Informational, not a problem
    WARNING = "warning"    # Potential issue, may need attention
    ERROR = "error"        # Definite problem that affects onboarding quality


class OnboardingIssueType(str, Enum):
    """Types of issues that can occur during onboarding."""
    COVERAGE_MISS = "coverage_miss"              # Explicit IDs mentioned but not in parsed config
    NORMALIZATION_REPAIR = "normalization_repair"  # Config was repaired during normalization
    ALT_CONFLICT = "alt_conflict"                # Alternative configs disagree on structure
    LLM_DISAGREEMENT = "llm_disagreement"        # Multiple LLM passes produced different results
    SIM_ANOMALY = "sim_anomaly"                  # Simulation revealed pathological behavior
    INPUT_CONTRADICTION = "input_contradiction"  # Input text contains contradictory info


class OnboardingTrust(str, Enum):
    """Trust levels for onboarded factory configs."""
    HIGH_TRUST = "HIGH_TRUST"      # Config is reliable, no conflicts, good coverage
    MEDIUM_TRUST = "MEDIUM_TRUST"  # Some repairs or minor disagreements
    LOW_TRUST = "LOW_TRUST"        # Conflicting configs or significant coverage misses


# =============================================================================
# ONBOARDING DIAGNOSTICS
# =============================================================================

class OnboardingIssue(BaseModel):
    """
    A single issue detected during onboarding.
    
    Issues are surfaced to help users understand why the parsed factory
    may not be fully accurate and what clarifications might help.
    """
    type: str = Field(..., description="Issue type (e.g., coverage_miss, normalization_repair)")
    severity: str = Field(..., description="Issue severity: info, warning, or error")
    message: str = Field(..., description="Human-readable description of the issue")
    related_ids: list[str] | None = Field(
        default=None, 
        description="Machine or job IDs related to this issue"
    )


# =============================================================================
# ERROR TYPES (Phase 3)
# =============================================================================

class ErrorInfo(BaseModel):
    """Structured error information for typed error handling."""
    type: ErrorType = Field(..., description="Category of error")
    message: str = Field(..., description="Human-readable error message")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context")
    recoverable: bool = Field(default=True, description="Whether this error might be recoverable")


# =============================================================================
# PLAN TYPES (Phase 1)
# =============================================================================

class PlanStep(BaseModel):
    """A single step in the agent's execution plan."""
    id: int = Field(..., description="Step index (0-based)")
    type: PlanStepType = Field(..., description="Type of step to execute")
    params: dict[str, Any] = Field(default_factory=dict, description="Parameters for this step")
    status: Literal["pending", "running", "done", "failed", "skipped"] = Field(
        default="pending", description="Current status of this step"
    )
    error: Optional[ErrorInfo] = Field(default=None, description="Error info if step failed")


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
    error_info: Optional[ErrorInfo] = None  # Structured error (Phase 3)


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
# PLANNING RESPONSE (LLM Output for Planning Phase)
# =============================================================================

class PlanResponse(BaseModel):
    """LLM response for the planning phase."""
    plan: list[dict[str, Any]] = Field(
        ...,
        description="List of plan steps with type and params"
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of why this plan was chosen"
    )


# =============================================================================
# FACTORY EXTRACTION INTERMEDIATE TYPES (Phase 2)
# =============================================================================

class FactoryEntities(BaseModel):
    """Intermediate result from entity extraction (Phase 2)."""
    machine_ids: list[str] = Field(default_factory=list)
    machine_names: dict[str, str] = Field(default_factory=dict)  # id -> name
    job_ids: list[str] = Field(default_factory=list)
    job_names: dict[str, str] = Field(default_factory=dict)  # id -> name


class FactoryRouting(BaseModel):
    """Intermediate result from routing extraction (Phase 2)."""
    job_routes: dict[str, list[str]] = Field(default_factory=dict)  # job_id -> [machine_ids]


class FactoryParameters(BaseModel):
    """Intermediate result from parameter extraction (Phase 2)."""
    processing_times: dict[str, dict[str, int]] = Field(default_factory=dict)  # job_id -> {machine_id -> hours}
    due_times: dict[str, int] = Field(default_factory=dict)  # job_id -> hour


class FactoryValidationReport(BaseModel):
    """Result of factory validation (Phase 2)."""
    valid: bool = Field(default=False)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage: dict[str, float] = Field(default_factory=dict)  # e.g., {"machines": 1.0, "jobs": 1.0}


# =============================================================================
# LLM CALL TRACKING (For Demo Observability)
# =============================================================================

class LLMCallRecord(BaseModel):
    """Record of a single LLM call for observability/demo purposes."""
    call_id: int = Field(..., description="Sequential call number")
    schema_name: str = Field(..., description="Pydantic schema the LLM was asked to produce")
    purpose: str = Field(default="", description="Human-readable purpose (e.g., 'Parse factory structure')")
    latency_ms: int = Field(..., description="Round-trip latency in milliseconds")
    input_tokens: int | None = Field(default=None, description="Input token count if available")
    output_tokens: int | None = Field(default=None, description="Output token count if available")
    step_id: int | None = Field(default=None, description="Which plan step triggered this call")


# =============================================================================
# DATA FLOW TRACKING (For Detailed Demo Visualization)
# =============================================================================

class OperationType(str, Enum):
    """Type of operation in the data flow."""
    FUNCTION = "function"      # Pure function call (🔧)
    LLM = "llm"               # LLM call (🤖)
    VALIDATION = "validation"  # Validation/check (✓)


class DataPreview(BaseModel):
    """Preview of data flowing through the system."""
    label: str = Field(..., description="Variable/parameter name")
    type_name: str = Field(..., description="Type name (e.g., 'str', 'FactoryConfig')")
    preview: str = Field(..., description="Truncated string representation")
    size: str | None = Field(default=None, description="Size info (e.g., '247 chars', '3 machines')")


class Operation(BaseModel):
    """A single operation (function call, LLM call, or validation) in the data flow."""
    id: str = Field(..., description="Unique operation ID")
    type: OperationType = Field(..., description="Type of operation")
    name: str = Field(..., description="Function/schema name")
    duration_ms: int = Field(default=0, description="Duration in milliseconds")
    inputs: list[DataPreview] = Field(default_factory=list, description="Input data previews")
    outputs: list[DataPreview] = Field(default_factory=list, description="Output data previews")
    # LLM-specific fields
    schema_name: str | None = Field(default=None, description="Pydantic schema name for LLM calls")
    input_tokens: int | None = Field(default=None, description="Input token count")
    output_tokens: int | None = Field(default=None, description="Output token count")
    error: str | None = Field(default=None, description="Error message if operation failed")


class DataFlowStep(BaseModel):
    """A step in the data flow (corresponds to a plan step or planning phase)."""
    step_id: int = Field(..., description="Step ID (-1 for planning phase)")
    step_type: str = Field(..., description="Step type (e.g., 'ensure_factory', 'planning')")
    step_name: str = Field(..., description="Human-readable step name")
    status: str = Field(default="pending", description="Step status")
    total_duration_ms: int = Field(default=0, description="Total duration")
    operations: list[Operation] = Field(default_factory=list, description="Operations in this step")
    step_input: DataPreview | None = Field(default=None, description="Primary input to this step")
    step_output: DataPreview | None = Field(default=None, description="Primary output from this step")


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
    - The execution plan and current position
    - LLM call budgets and error tracking
    
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
    
    # Phase 4: LLM call budget
    llm_call_budget: int = Field(default=10, description="Maximum LLM calls allowed")
    error_budget: int = Field(default=3, description="Maximum errors before aborting")
    
    # =========================================================================
    # EXECUTION STATE (Mutable, updated each loop)
    # =========================================================================
    status: AgentStatus = Field(default=AgentStatus.RUNNING)
    steps: int = Field(default=0, description="Current step count")
    consecutive_errors: int = Field(default=0, description="Errors in a row (resets on success)")
    
    # Phase 4: LLM call tracking
    llm_calls_used: int = Field(default=0, description="Number of LLM calls made so far")
    
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
    # PLAN STATE (Phase 1)
    # =========================================================================
    plan: list[PlanStep] = Field(
        default_factory=list,
        description="The agent's execution plan (populated at step 0)"
    )
    active_step_index: Optional[int] = Field(
        default=None,
        description="Index of currently executing plan step"
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
    
    # Phase 2: Intermediate parsing state
    factory_entities: Optional[FactoryEntities] = Field(
        default=None,
        description="Extracted entities (machines, jobs) from parsing"
    )
    factory_routing: Optional[FactoryRouting] = Field(
        default=None,
        description="Extracted routing info from parsing"
    )
    factory_parameters: Optional[FactoryParameters] = Field(
        default=None,
        description="Extracted parameters from parsing"
    )
    
    # Internal intermediate extraction results (not serialized, for tool reuse)
    # These store raw LLM outputs so subsequent tools don't re-call
    _coarse_structure: Any = PrivateAttr(default=None)  # CoarseStructure from extract_coarse_structure
    _raw_factory_config: Any = PrivateAttr(default=None)  # RawFactoryConfig from extract_steps
    
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
    # ERROR TRACKING (Phase 3)
    # =========================================================================
    errors_encountered: list[ErrorInfo] = Field(
        default_factory=list,
        description="All errors encountered during execution"
    )
    
    # =========================================================================
    # ONBOARDING DIAGNOSTICS (For Robust Onboarding)
    # =========================================================================
    onboarding_issues: list[OnboardingIssue] = Field(
        default_factory=list,
        description="Issues detected during factory onboarding (coverage misses, repairs, conflicts)"
    )
    onboarding_score: Optional[int] = Field(
        default=None,
        description="Onboarding quality score (0-100, None if not computed)"
    )
    onboarding_trust: Optional[str] = Field(
        default=None,
        description="Trust level: HIGH_TRUST, MEDIUM_TRUST, or LOW_TRUST"
    )
    
    # Alternative configs from multi-pass onboarding (PR9)
    alt_factories: list[FactoryConfig] = Field(
        default_factory=list,
        description="Alternative factory interpretations from multi-pass extraction"
    )
    alt_factory_modes: list[str] = Field(
        default_factory=list,
        description="Extraction modes that produced each alternative config"
    )
    diff_summaries: list[str] = Field(
        default_factory=list,
        description="Human-readable summaries of differences between primary and each alternative"
    )
    alt_factory_diffs: list[Any] = Field(
        default_factory=list,
        description="Structured FactoryDiff objects between primary and each alternative"
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Targeted questions generated from config differences"
    )
    
    # =========================================================================
    # LLM CALL TRACKING (For Demo Observability)
    # =========================================================================
    llm_calls: list[LLMCallRecord] = Field(
        default_factory=list,
        description="Record of all LLM calls made during execution"
    )
    
    # =========================================================================
    # DATA FLOW TRACKING (For Detailed Demo Visualization)
    # =========================================================================
    data_flow: list[DataFlowStep] = Field(
        default_factory=list,
        description="Detailed data flow through the system"
    )
    _current_data_flow_step: Optional["DataFlowStep"] = PrivateAttr(default=None)
    
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
    
    def increment_llm_calls(self) -> bool:
        """
        Increment LLM call counter. Returns True if under budget, False if exceeded.
        """
        self.llm_calls_used += 1
        if self.llm_calls_used > self.llm_call_budget:
            self.status = AgentStatus.BUDGET_EXCEEDED
            return False
        return True
    
    def record_error(self, error: str, error_info: Optional[ErrorInfo] = None) -> None:
        """Track consecutive errors for retry logic."""
        self.consecutive_errors += 1
        self.add_thought(f"ERROR: {error}")
        
        if error_info:
            self.errors_encountered.append(error_info)
        
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
    
    def record_llm_call(
        self, 
        schema_name: str, 
        latency_ms: int,
        purpose: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Record an LLM call for observability."""
        call_id = len(self.llm_calls) + 1
        self.llm_calls.append(LLMCallRecord(
            call_id=call_id,
            schema_name=schema_name,
            purpose=purpose,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            step_id=self.active_step_index,
        ))
    
    # =========================================================================
    # DATA FLOW HELPERS
    # =========================================================================
    
    def start_data_flow_step(
        self,
        step_id: int,
        step_type: str,
        step_name: str,
        step_input: DataPreview | None = None,
    ) -> None:
        """Start tracking a new data flow step."""
        self._current_data_flow_step = DataFlowStep(
            step_id=step_id,
            step_type=step_type,
            step_name=step_name,
            status="running",
            step_input=step_input,
        )
    
    def add_operation(
        self,
        op_type: OperationType,
        name: str,
        duration_ms: int = 0,
        inputs: list[DataPreview] | None = None,
        outputs: list[DataPreview] | None = None,
        schema_name: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
    ) -> None:
        """Add an operation to the current data flow step."""
        if self._current_data_flow_step is None:
            return  # No active step, skip
        
        op_id = f"{self._current_data_flow_step.step_id}_{len(self._current_data_flow_step.operations)}"
        op = Operation(
            id=op_id,
            type=op_type,
            name=name,
            duration_ms=duration_ms,
            inputs=inputs or [],
            outputs=outputs or [],
            schema_name=schema_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error,
        )
        self._current_data_flow_step.operations.append(op)
        self._current_data_flow_step.total_duration_ms += duration_ms
    
    def finish_data_flow_step(
        self,
        status: str = "done",
        step_output: DataPreview | None = None,
    ) -> None:
        """Finish the current data flow step and add it to the flow."""
        if self._current_data_flow_step is None:
            return
        
        self._current_data_flow_step.status = status
        if step_output:
            self._current_data_flow_step.step_output = step_output
        
        self.data_flow.append(self._current_data_flow_step)
        self._current_data_flow_step = None
    
    def mark_plan_step_running(self, step_id: int) -> None:
        """Mark a plan step as running."""
        for step in self.plan:
            if step.id == step_id:
                step.status = "running"
                self.active_step_index = step_id
                break
    
    def mark_plan_step_done(self, step_id: int) -> None:
        """Mark a plan step as done."""
        for step in self.plan:
            if step.id == step_id:
                step.status = "done"
                break
    
    def mark_plan_step_failed(self, step_id: int, error_info: ErrorInfo) -> None:
        """Mark a plan step as failed with error info."""
        for step in self.plan:
            if step.id == step_id:
                step.status = "failed"
                step.error = error_info
                break
    
    def get_next_pending_step(self) -> Optional[PlanStep]:
        """Get the next pending step in the plan."""
        for step in self.plan:
            if step.status == "pending":
                return step
        return None
    
    def get_plan_summary(self) -> str:
        """Get a human-readable summary of the plan."""
        if not self.plan:
            return "No plan set"
        
        parts = []
        for step in self.plan:
            status_icon = {
                "pending": "○",
                "running": "▶",
                "done": "✓",
                "failed": "✗",
                "skipped": "−",
            }.get(step.status, "?")
            
            param_str = ""
            if step.params:
                param_str = f"({', '.join(f'{k}={v}' for k, v in step.params.items())})"
            
            parts.append(f"{status_icon} {step.type.value}{param_str}")
        
        return " → ".join(parts)
    
    # =========================================================================
    # ONBOARDING DIAGNOSTICS HELPERS
    # =========================================================================
    
    def add_onboarding_issue(
        self,
        issue_type: str,
        severity: str,
        message: str,
        related_ids: list[str] | None = None,
    ) -> None:
        """
        Add an onboarding issue to the state.
        
        Args:
            issue_type: Type of issue (e.g., "coverage_miss", "normalization_repair")
            severity: Severity level ("info", "warning", "error")
            message: Human-readable description
            related_ids: Optional list of machine/job IDs related to this issue
        """
        self.onboarding_issues.append(OnboardingIssue(
            type=issue_type,
            severity=severity,
            message=message,
            related_ids=related_ids,
        ))
    
    def set_onboarding_score(self, score: int, trust: str) -> None:
        """
        Set the onboarding quality score and trust level.
        
        Args:
            score: Quality score (0-100)
            trust: Trust level ("HIGH_TRUST", "MEDIUM_TRUST", "LOW_TRUST")
        """
        self.onboarding_score = score
        self.onboarding_trust = trust
    
    def set_alternative_factories(
        self,
        alt_factories: list[FactoryConfig],
        alt_modes: list[str],
        diff_summaries: list[str],
        diffs: list[Any] | None = None,
        questions: list[str] | None = None,
    ) -> None:
        """
        Set alternative factory interpretations from multi-pass extraction.

        Args:
            alt_factories: List of alternative FactoryConfig objects
            alt_modes: Extraction modes that produced each alternative
            diff_summaries: Human-readable diff summaries for each alternative
            diffs: Structured FactoryDiff objects for each alternative
            questions: Targeted clarifying questions derived from diffs
        """
        self.alt_factories = alt_factories
        self.alt_factory_modes = alt_modes
        self.diff_summaries = diff_summaries
        self.alt_factory_diffs = diffs or []
        self.clarifying_questions = questions or []