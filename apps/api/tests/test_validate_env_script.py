import os
import subprocess
import sys
from pathlib import Path


def test_validate_env_runs_standalone_without_exposing_configuration() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["VPN_SALE_ENVIRONMENT"] = "local"
    sensitive_marker = "sensitive-output-marker"
    environment["VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY"] = sensitive_marker

    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, "scripts/validate-env.py"],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Environment configuration is valid."
    assert sensitive_marker not in result.stdout
