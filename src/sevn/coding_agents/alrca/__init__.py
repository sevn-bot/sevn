"""ALRCA — Autonomous Long-Running Coding Agent orchestrator core (CA3).

Module: sevn.coding_agents.alrca
Depends: sevn.coding_agents.alrca.goal, sevn.coding_agents.alrca.loop_worker,
    sevn.coding_agents.alrca.evaluator, sevn.coding_agents.alrca.verifiers

Exports:
    GoalContract, GoalStatus, new_goal, load_goal, save_goal, list_goals
    EvaluatorResult, evaluate_turn
    VerifierResult, build_verifier, run_verifier_spec
    ALRCALoopWorker, LoopResult
"""

from sevn.coding_agents.alrca.evaluator import EvaluatorResult, evaluate_turn
from sevn.coding_agents.alrca.goal import (
    GoalContract,
    GoalStatus,
    list_goals,
    load_goal,
    new_goal,
    save_goal,
)
from sevn.coding_agents.alrca.loop_worker import ALRCALoopWorker, LoopResult, run_alrca_loop
from sevn.coding_agents.alrca.verifiers import (
    VerifierResult,
    build_verifier,
    run_verifier_spec,
)

__all__ = [
    "ALRCALoopWorker",
    "EvaluatorResult",
    "GoalContract",
    "GoalStatus",
    "LoopResult",
    "VerifierResult",
    "build_verifier",
    "evaluate_turn",
    "list_goals",
    "load_goal",
    "new_goal",
    "run_alrca_loop",
    "run_verifier_spec",
    "save_goal",
]
