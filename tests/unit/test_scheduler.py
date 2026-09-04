from datetime import UTC, datetime, timedelta

from backend.scheduler import build_scheduler, schedule_action


def scheduler_handler(_: str) -> None:
    return None


def test_scheduled_action_survives_scheduler_restart(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'scheduler.sqlite').as_posix()}"
    action_id = "action-restart-test"
    run_at = datetime.now(UTC) + timedelta(hours=1)

    first = build_scheduler(database_url, scheduler_handler)
    first.start(paused=True)
    schedule_action(first, action_id, run_at)
    first.shutdown(wait=False)

    second = build_scheduler(database_url, scheduler_handler)
    second.start(paused=True)
    try:
        job = second.get_job(f"recovery-action:{action_id}")
        assert job is not None
        assert job.args == (action_id,)
    finally:
        second.shutdown(wait=False)
