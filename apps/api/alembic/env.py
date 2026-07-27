import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alembic import context
from sqlalchemy import Connection, MetaData, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from platform_api.identity.models import IdentityBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _target_metadata() -> MetaData:
    # Historical revisions must not see future ORM tables during normal upgrade
    # execution. Import feature model modules only for Alembic autogenerate so
    # developer workflows still compare against the full current metadata.
    cmd_opts = getattr(config, "cmd_opts", None)
    if bool(getattr(cmd_opts, "autogenerate", False)):
        import platform_api.catalog_models  # noqa: F401
        import platform_api.configuration_models  # noqa: F401
        import platform_api.customer_admin_models  # noqa: F401
        import platform_api.customer_auth.models  # noqa: F401
        import platform_api.delivery_models  # noqa: F401
        import platform_api.notification_preferences  # noqa: F401
        import platform_api.order_models  # noqa: F401
        import platform_api.payment_models  # noqa: F401
        import platform_api.service_models  # noqa: F401
        import platform_api.wallet_models  # noqa: F401
    return IdentityBase.metadata


target_metadata = _target_metadata()

database_url = os.environ.get("VPN_SALE_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
