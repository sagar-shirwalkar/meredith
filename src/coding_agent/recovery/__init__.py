"""
Recovery subsystem: loop detection and escape strategies.

Prevents the agent from getting stuck in repetitive cycles
by detecting loops and injecting corrective interventions.
"""

from coding_agent.recovery.detector import LoopDetector
from coding_agent.recovery.strategies import LoopRecovery

__all__ = [
    "LoopDetector",
    "LoopRecovery",
]
