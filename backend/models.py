from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class ScenarioType(str, Enum):
    """Scenario types for factory simulation."""
    BASELINE = "BASELINE"
    RUSH_ARRIVES = "RUSH_ARRIVES"
    M2_SLOWDOWN = "M2_SLOWDOWN"


class Machine(BaseModel):
    """Represents a factory machine."""
    id: str = Field(..., description="Unique machine ID, e.g., 'M1'")
    name: str = Field(..., description="Human-readable machine name")


class Step(BaseModel):
    """Represents one step in a job's routing."""
    machine_id: str = Field(..., description="Machine ID where this step runs")
    duration_hours: int = Field(..., description="Integer duration in hours")


class Job(BaseModel):
    """Represents a factory job with multiple steps."""
    id: str = Field(..., description="Unique job ID, e.g., 'J1'")
    name: str = Field(..., description="Human-readable job name")
    steps: list[Step] = Field(..., description="Ordered sequence of steps")
    due_time_hour: int = Field(..., description="Integer hour by which job is due")


class FactoryConfig(BaseModel):
    """Configuration for the entire factory."""
    machines: list[Machine] = Field(..., description="List of all machines")
    jobs: list[Job] = Field(..., description="List of all jobs")

    def validate_unique_ids(self):
        """Validate that machines and jobs have unique IDs."""
        machine_ids = [m.id for m in self.machines]
        job_ids = [j.id for j in self.jobs]

        if len(machine_ids) != len(set(machine_ids)):
            raise ValueError("Duplicate machine IDs")
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("Duplicate job IDs")


class ScheduledStep(BaseModel):
    """Represents a single scheduled step in the simulation result."""
    job_id: str = Field(..., description="Job ID this step belongs to")
    machine_id: str = Field(..., description="Machine ID where step runs")
    step_index: int = Field(..., description="Index in the job's steps list")
    start_hour: int = Field(..., description="Integer hour when step starts")
    end_hour: int = Field(..., description="Integer hour when step ends (exclusive)")


class SimulationResult(BaseModel):
    """Result of a baseline simulation run."""
    scheduled_steps: list[ScheduledStep] = Field(..., description="All scheduled steps")
    job_completion_times: dict[str, int] = Field(..., description="Job ID -> completion hour")
    makespan_hour: int = Field(..., description="Total hours from 0 to last completion")


class ScenarioSpec(BaseModel):
    """
    Specification of a single what-if scenario to apply to the baseline factory.

    - BASELINE: no changes to the factory.
    - RUSH_ARRIVES: treat an existing job as a rush/prioritized job by tightening its due time.
    - M2_SLOWDOWN: slow down machine M2 by an integer slowdown_factor >= 2.
    """

    scenario_type: ScenarioType = Field(..., description="Type of scenario to apply")
    rush_job_id: Optional[str] = Field(default=None, description="Job ID for RUSH_ARRIVES scenario")
    slowdown_factor: Optional[int] = Field(default=None, description="Slowdown multiplier for M2_SLOWDOWN scenario")

    @model_validator(mode="after")
    def validate_scenario_fields(self):
        """Validate that scenario fields are consistent with scenario_type."""
        if self.scenario_type == ScenarioType.BASELINE:
            if self.rush_job_id is not None:
                raise ValueError("BASELINE scenario must have rush_job_id=None")
            if self.slowdown_factor is not None:
                raise ValueError("BASELINE scenario must have slowdown_factor=None")
        elif self.scenario_type == ScenarioType.RUSH_ARRIVES:
            if self.rush_job_id is None or self.rush_job_id == "":
                raise ValueError("RUSH_ARRIVES scenario requires a non-empty rush_job_id")
            if self.slowdown_factor is not None:
                raise ValueError("RUSH_ARRIVES scenario must have slowdown_factor=None")
        elif self.scenario_type == ScenarioType.M2_SLOWDOWN:
            if self.slowdown_factor is None or self.slowdown_factor < 2:
                raise ValueError("M2_SLOWDOWN scenario requires slowdown_factor >= 2")
            if self.rush_job_id is not None:
                raise ValueError("M2_SLOWDOWN scenario must have rush_job_id=None")
        return self


class ScenarioMetrics(BaseModel):
    """Aggregate performance metrics for a single simulation run."""

    makespan_hour: int = Field(..., description="Total makespan in integer hours")
    job_lateness: dict[str, int] = Field(..., description="Job ID -> lateness in hours (>= 0)")
    bottleneck_machine_id: str = Field(..., description="Machine ID with highest total busy time")
    bottleneck_utilization: float = Field(..., description="Utilization of bottleneck machine (0.0 to 1.0)")

    @model_validator(mode="after")
    def validate_metrics(self):
        """Validate metrics constraints."""
        if self.makespan_hour < 0:
            raise ValueError("makespan_hour must be non-negative")
        for job_id, lateness in self.job_lateness.items():
            if not isinstance(lateness, int):
                raise ValueError(f"lateness for {job_id} must be an integer")
            if lateness < 0:
                raise ValueError(f"lateness for {job_id} must be non-negative")
        if not (0.0 <= self.bottleneck_utilization <= 1.0):
            raise ValueError("bottleneck_utilization must be between 0.0 and 1.0")
        return self
