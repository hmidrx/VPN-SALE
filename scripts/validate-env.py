import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "apps" / "api" / "src"))

from platform_api.config import get_settings, validate_security_configuration  # noqa: E402

settings = get_settings()
validate_security_configuration(settings)
print("Environment configuration is valid.")
