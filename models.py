from enum import Enum
from pydantic import BaseModel, Field


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
