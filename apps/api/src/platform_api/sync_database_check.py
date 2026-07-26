from __future__ import annotations

import os

import psycopg
from sqlalchemy import text

from .database import get_engine


def main() -> int:
    engine = None
    try:
        if os.geteuid() == 0 or not psycopg.__version__:
            raise RuntimeError
        engine = get_engine()
        with engine.connect() as connection:
            if connection.execute(text("SELECT 1")).scalar_one() != 1:
                raise RuntimeError
    except Exception:  # noqa: BLE001 - this verifier deliberately emits no connection details
        print("FAIL")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
