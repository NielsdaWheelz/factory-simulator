"""
Factory World Definition Module

This module defines the toy factory world:
- Function: build_toy_factory() -> FactoryConfig
- 3 machines (M1: Assembly, M2: Drill/Mill, M3: Pack/Ship)
- 3 jobs (J1, J2, J3) with integer hour durations
- Shared bottleneck on M2 creating realistic scheduling conflicts
"""

from .models import FactoryConfig, Machine, Job, Step


def build_toy_factory() -> FactoryConfig:
    """
    Build a toy factory with 3 machines and 3 jobs.

    All three jobs contend for M2, making it the bottleneck.
    Uses simple integer durations (1-3 hours per step).

    Returns:
        FactoryConfig: immutable factory configuration
    """
    # Define 3 machines
    machines = [
        Machine(id="M1", name="Assembly"),
        Machine(id="M2", name="Drill/Mill"),
        Machine(id="M3", name="Pack/Ship"),
    ]

    # Define 3 jobs with M2 contention
    # J1: M1(1h) -> M2(3h) -> M3(1h) = 5h total, due at 12h
    job_j1 = Job(
        id="J1",
        name="Widget A",
        steps=[
            Step(machine_id="M1", duration_hours=1),
            Step(machine_id="M2", duration_hours=3),
            Step(machine_id="M3", duration_hours=1),
        ],
        due_time_hour=12,
    )

    # J2: M1(1h) -> M2(2h) -> M3(1h) = 4h total, due at 14h
    job_j2 = Job(
        id="J2",
        name="Gadget B",
        steps=[
            Step(machine_id="M1", duration_hours=1),
            Step(machine_id="M2", duration_hours=2),
            Step(machine_id="M3", duration_hours=1),
        ],
        due_time_hour=14,
    )

    # J3: M2(1h) -> M3(2h) = 3h total, due at 16h
    job_j3 = Job(
        id="J3",
        name="Part C",
        steps=[
            Step(machine_id="M2", duration_hours=1),
            Step(machine_id="M3", duration_hours=2),
        ],
        due_time_hour=16,
    )

    jobs = [job_j1, job_j2, job_j3]

    return FactoryConfig(machines=machines, jobs=jobs)
