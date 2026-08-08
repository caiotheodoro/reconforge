"""ReconForge Forge — measurement core of ReconForge."""

from reconforge_forge import taxonomy
from reconforge_forge.task import Task

__version__ = "0.1.0"

from reconforge_forge.generator import generate_tasks
from reconforge_forge.verifier import verify_task
from reconforge_forge.benchmark import run_pilot, score_verdicts
from reconforge_forge.contamination import signatures, leak_probe, evaluate_monitor

__all__ = [
    "Task",
    "taxonomy",
    "generate_tasks",
    "verify_task",
    "run_pilot",
    "score_verdicts",
    "signatures",
    "leak_probe",
    "evaluate_monitor",
]
