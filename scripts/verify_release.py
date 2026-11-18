from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=BACKEND, env=env, check=True)


def main() -> int:
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
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
        test_env = env.copy()
        test_env["ENFORCE_AUTHORIZATION"] = "false"
        run([sys.executable, "-m", "pytest", "-q"], test_env)
    print("EPIC release verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
