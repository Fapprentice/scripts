"""Tests for the shared desktop/CI service composition seam."""

from application import ServiceContext, build_services
from state_store import SqliteStore


def test_build_services_uses_one_companion_for_task_and_acceptance(tmp_path):
    calls = []
    context = ServiceContext(
        text=str, normalize=lambda value: value, goal_id=lambda _: "g1",
        sync_pct=lambda _: None, save=lambda _: None, event=lambda *args: None,
        undo=lambda *args: None, compact=lambda _: None, outcome=lambda *args: None,
        readiness=lambda _: {"ready": True}, first_task_started=lambda _: None,
        agent_orchestrator=lambda: None,
        submit=lambda function, *args, **kwargs: calls.append((function, args, kwargs)),
        agent_loop=lambda *args: None, feedback_record=lambda *args: None,
        done=lambda _: False, learning_outcome=lambda *args: None,
    )
    bundle = build_services(SqliteStore(tmp_path, auto_backup=False), context)
    assert bundle.tasks.companion is not None
    assert bundle.acceptance.companion is not None
    assert bundle.companion is not None
