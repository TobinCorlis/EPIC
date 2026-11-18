from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
LEGACY_CLAIM_SUPPORTED = "legacy: not recorded"
COUNTED_TABLES = (
    "users",
    "auth_sessions",
    "debates",
    "claims",
    "sources",
    "citations",
    "claim_evidence",
    "participants",
    "argument_nodes",
    "evidence_challenges",
    "moderator_rulings",
    "topic_dossiers",
    "dossier_sources",
    "knowledge_claims",
    "claim_contradictions",
    "research_jobs",
    "research_job_events",
    "debate_invitations",
    "debate_events",
    "debate_room_states",
    "debate_turns",
    "turn_moderation_reviews",
)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def baseline_commit() -> str:
    for ref in ("import/epic-v1.0-rc2", "origin/import/epic-v1.0-rc2"):
        found = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if found.returncode == 0:
            return found.stdout.strip()
    listing = subprocess.run(
        ["git", "rev-list", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for sha in listing.stdout.split():
        files = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", sha, "backend/alembic/versions"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if "0004_turn_moderation.py" in files and "0005_verification_events.py" not in files:
            return sha
    raise SystemExit(
        "Could not find the unmodified v1.0-rc2 commit. Fetch full history before running this check."
    )


def base_env(database_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "testing",
            "DATABASE_URL": database_url,
            "SECRET_KEY": "release-verification-secret",
            "AUTO_CREATE_SCHEMA": "false",
            "ENFORCE_AUTHORIZATION": "false",
            "ALLOWED_ORIGINS": '["http://testserver"]',
            "TRUSTED_HOSTS": '["testserver", "localhost", "127.0.0.1"]',
        }
    )
    return env


def scalar(url: str, statement: str) -> object:
    engine = create_engine(url)
    with engine.connect() as connection:
        value = connection.execute(text(statement)).scalar()
    engine.dispose()
    return value


def rows(url: str, statement: str) -> list[tuple]:
    engine = create_engine(url)
    with engine.connect() as connection:
        found = connection.execute(text(statement)).fetchall()
    engine.dispose()
    return [tuple(row) for row in found]


def counts(url: str) -> dict[str, int]:
    return {table: int(scalar(url, f"SELECT COUNT(*) FROM {table}")) for table in COUNTED_TABLES}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def assert_upgraded(url: str, before: dict[str, int]) -> None:
    after = counts(url)
    require(after == before, f"Row counts changed during upgrade:\n before={before}\n after={after}")
    require(
        scalar(
            url,
            """
            SELECT COUNT(*) FROM argument_nodes
            WHERE verification_status = 'verified'
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'argument_node'
                  AND subject_id = argument_nodes.id
                  AND result_status = 'verified'
              )
            """,
        )
        == 0,
        "An argument stayed verified without a verification event",
    )
    require(
        scalar(
            url,
            """
            SELECT COUNT(*) FROM knowledge_claims
            WHERE status = 'verified'
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'knowledge_claim'
                  AND subject_id = knowledge_claims.id
                  AND result_status = 'verified'
              )
            """,
        )
        == 0,
        "A knowledge claim stayed verified without a verification event",
    )
    require(
        rows(url, "SELECT claim_supported FROM claim_evidence ORDER BY id")
        == [(LEGACY_CLAIM_SUPPORTED,), (LEGACY_CLAIM_SUPPORTED,)],
        "Existing evidence links did not keep the legacy placeholder",
    )
    require(
        rows(
            url,
            "SELECT verification_status FROM argument_nodes WHERE body LIKE 'The agency page%' ",
        )
        == [("unverified",)],
        "The seeded allowed/verified argument was not marked unverified",
    )
    require(
        rows(url, "SELECT verification_status FROM argument_nodes WHERE body LIKE 'Therefore%'")
        == [("pending",)],
        "The pending argument changed status",
    )
    require(
        rows(
            url,
            "SELECT status, confidence_score FROM knowledge_claims WHERE body LIKE 'The agency report%'",
        )
        == [("unverified", None)],
        "The seeded verified knowledge claim was not demoted to unknown confidence",
    )
    require(
        scalar(
            url,
            "SELECT note FROM status_history WHERE subject_type = 'knowledge_claim' AND previous_status = 'verified'",
        )
        == "Marked verified in rc2; no verification record found",
        "The knowledge-claim history note was not kept",
    )
    require(
        scalar(
            url,
            "SELECT note FROM status_history WHERE subject_type = 'argument_node' AND previous_status = 'verified'",
        )
        == "Marked verified in rc2; no verification record found",
        "The argument history note was not kept",
    )
    require(scalar(url, "SELECT COUNT(*) FROM verification_events") == 0, "Upgrade invented a verification event")
    require(
        scalar(url, "SELECT COUNT(*) FROM claims WHERE body LIKE 'The agency report%'") == 1,
        "A seeded claim body was lost",
    )
    require(
        scalar(url, "SELECT COUNT(*) FROM moderator_rulings WHERE outcome = 'allowed'") == 1,
        "The allowed ruling was lost",
    )


def assert_downgraded(url: str, before: dict[str, int]) -> None:
    require(counts(url) == before, "Downgrade changed row counts")
    require(
        rows(url, "SELECT verification_status FROM argument_nodes WHERE body LIKE 'The agency page%'")
        == [("unreviewed",)],
        "Downgrade restored a verified label that has no verification event",
    )
    require(
        rows(url, "SELECT status FROM knowledge_claims WHERE body LIKE 'The agency report%'") == [("candidate",)],
        "Downgrade restored a verified knowledge claim",
    )
    evidence_columns = {row[0] for row in rows(url, "SELECT column_name FROM information_schema.columns WHERE table_name = 'claim_evidence'" if url.startswith("postgresql") else "SELECT name FROM pragma_table_info('claim_evidence')")}
    require("claim_supported" not in evidence_columns, "Downgrade left claim_supported in place")


def upgrade_database(url: str, baseline_backend: Path) -> None:
    env = base_env(url)
    print(f"Baseline migrate {url}")
    run([sys.executable, "-m", "alembic", "upgrade", "head"], baseline_backend, env)
    seed_env = env.copy()
    seed_env["PYTHONPATH"] = str(baseline_backend)
    print("Seed rc2 fixture")
    run([sys.executable, str(ROOT / "scripts" / "seed_rc2_fixture.py")], baseline_backend, seed_env)
    before = counts(url)
    print(f"Upgrade seeded database to head ({url})")
    run([sys.executable, "-m", "alembic", "upgrade", "head"], BACKEND, env)
    assert_upgraded(url, before)
    print(f"Downgrade seeded database to rc2 head ({url})")
    run([sys.executable, "-m", "alembic", "downgrade", "0004"], BACKEND, env)
    assert_downgraded(url, before)
    print(f"Upgrade again after downgrade ({url})")
    run([sys.executable, "-m", "alembic", "upgrade", "head"], BACKEND, env)
    require(counts(url) == before, "Second upgrade changed row counts")
    require(
        scalar(
            url,
            "SELECT COUNT(*) FROM argument_nodes WHERE verification_status = 'verified'",
        )
        == 0,
        "Second upgrade left an argument verified",
    )


def reset_postgres(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def check_baseline_upgrade(baseline_backend: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="epic-upgrade-") as tmp:
        sqlite_url = f"sqlite:///{Path(tmp) / 'upgrade.db'}"
        upgrade_database(sqlite_url, baseline_backend)
    postgres_url = os.environ.get("EPIC_UPGRADE_POSTGRES_URL")
    if not postgres_url:
        print("PostgreSQL upgrade check skipped (set EPIC_UPGRADE_POSTGRES_URL to run it).")
        return
    print("Resetting the disposable PostgreSQL database named by EPIC_UPGRADE_POSTGRES_URL")
    reset_postgres(postgres_url)
    upgrade_database(postgres_url, baseline_backend)


def fresh_suite() -> None:
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="epic-release-") as tmp:
        db_path = Path(tmp) / "release.db"
        env.update(
            {
                "APP_ENV": "testing",
                "DATABASE_URL": f"sqlite:///{db_path}",
                "SECRET_KEY": "release-verification-secret",
                "AUTO_CREATE_SCHEMA": "false",
                "ENFORCE_AUTHORIZATION": "true",
                "ALLOWED_ORIGINS": '["http://testserver"]',
                "TRUSTED_HOSTS": '["testserver", "localhost", "127.0.0.1"]',
            }
        )
        run([sys.executable, "-m", "alembic", "upgrade", "head"], BACKEND, env)
        test_env = env.copy()
        test_env["ENFORCE_AUTHORIZATION"] = "false"
        run([sys.executable, "-m", "pytest", "-q"], BACKEND, test_env)


def main() -> int:
    fresh_suite()
    commit = baseline_commit()
    print("Baseline commit", commit)
    with tempfile.TemporaryDirectory(prefix="epic-baseline-") as tmp:
        worktree = Path(tmp) / "baseline"
        run(["git", "worktree", "add", "--detach", str(worktree), commit], ROOT)
        try:
            check_baseline_upgrade(worktree / "backend")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=ROOT, check=False)
    print("EPIC release verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
