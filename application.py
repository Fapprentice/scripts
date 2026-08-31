"""Application composition seam shared by desktop and CI hosts."""

from dataclasses import dataclass

from acceptance_service import AcceptanceService
from agent_service import AgentService
from companion_service import CompanionService
from feedback_service import FeedbackService
from task_service import TaskService


@dataclass(frozen=True)
class ServiceContext:
    """Host callbacks needed to compose the domain services.

    The services remain independent of the desktop entry point; this is the
    single adapter seam for persistence, scheduling, and application policy.
    """

    text: object
    normalize: object
    goal_id: object
    sync_pct: object
    save: object
    event: object
    undo: object
    compact: object
    outcome: object
    readiness: object
    first_task_started: object
    agent_orchestrator: object
    submit: object
    agent_loop: object
    feedback_record: object
    done: object
    learning_outcome: object


@dataclass
class ServiceBundle:
    companion: CompanionService
    tasks: TaskService
    agents: AgentService
    feedback: FeedbackService
    acceptance: AcceptanceService


def build_services(store, context):
    """Build the complete domain service graph for any host."""
    companion = CompanionService(store)
    tasks = TaskService(
        text=context.text, normalize=context.normalize, goal_id=context.goal_id,
        sync_pct=context.sync_pct, save=context.save, event=context.event,
        undo=context.undo, compact=context.compact, outcome=context.outcome,
        readiness=context.readiness, first_task_started=context.first_task_started,
        companion=lambda state, idx, previous, status: companion.on_status(
            state, idx, previous, status, commit=False),
    )
    agents = AgentService(
        lambda: context.agent_orchestrator(),
        start_loop=lambda run_id: context.submit(
            context.agent_loop, run_id, key="agent:" + run_id),
    )
    feedback = FeedbackService(
        record=context.feedback_record, done=context.done,
        sync_pct=context.sync_pct, save=context.save,
        event=context.event, compact=context.compact,
    )
    acceptance = AcceptanceService(
        normalize=context.normalize, text=context.text, sync_pct=context.sync_pct,
        save=context.save, event=context.event, outcome=context.outcome,
        learning_outcome=context.learning_outcome,
        companion=lambda state, idx, result: companion.on_acceptance(
            state, idx, result, commit=False),
    )
    return ServiceBundle(companion, tasks, agents, feedback, acceptance)
