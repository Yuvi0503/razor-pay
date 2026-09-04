import os
import shutil
import subprocess
from collections.abc import Sequence

import pytest

EXPECTED_TABLES = (
    "merchants",
    "customers",
    "customer_consent",
    "orders",
    "subscriptions",
    "payment_attempts",
    "recovery_cases",
    "recovery_decisions",
    "policy_evaluations",
    "recovery_actions",
    "human_approvals",
    "outbound_messages",
    "audit_events",
    "raw_events",
)


def run(command: Sequence[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def require_success(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, f"Command failed:\n{result.stdout}\n{result.stderr}"
    return (result.stdout or "").strip()


def test_clean_postgres_migration_with_docker_compose() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")
    daemon = run((docker, "info"), timeout=30)
    if daemon.returncode != 0:
        pytest.skip("Docker daemon is not available")

    project = f"revenue-recovery-migration-{os.getpid()}"
    compose = (docker, "compose", "-p", project, "-f", "docker-compose.yml")
    try:
        require_success(run(compose + ("up", "-d", "--wait", "db"), timeout=180))
        require_success(
            run(
                compose
                + ("run", "--rm", "--build", "--no-deps", "api", "alembic", "upgrade", "head"),
                timeout=300,
            )
        )

        table_query = (
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN "
            "(" + ",".join(f"'{table}'" for table in EXPECTED_TABLES) + ");"
        )
        table_count = require_success(
            run(
                compose
                + (
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "recovery",
                    "-d",
                    "recovery",
                    "-Atqc",
                    table_query,
                )
            )
        )
        assert int(table_count) == len(EXPECTED_TABLES)

        column_query = (
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='policy_evaluations' "
            "AND column_name='policy_config_hash';"
        )
        assert (
            require_success(
                run(
                    compose
                    + (
                        "exec",
                        "-T",
                        "db",
                        "psql",
                        "-U",
                        "recovery",
                        "-d",
                        "recovery",
                        "-Atqc",
                        column_query,
                    )
                )
            )
            == "1"
        )

        trigger_query = (
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname IN ('payment_attempts','audit_events');"
        )
        assert (
            require_success(
                run(
                    compose
                    + (
                        "exec",
                        "-T",
                        "db",
                        "psql",
                        "-U",
                        "recovery",
                        "-d",
                        "recovery",
                        "-Atqc",
                        trigger_query,
                    )
                )
            )
            == "2"
        )
    finally:
        run(compose + ("down", "--volumes", "--remove-orphans"), timeout=180)
