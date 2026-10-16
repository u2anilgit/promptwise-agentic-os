# core/migrations/env.py — online migrations only, engine supplied by core.db.migrate.
from alembic import context

import core.spec.tables  # noqa: F401 — register tables on Base.metadata
from core.db.base import Base

target_metadata = Base.metadata
config = context.config


def run_migrations_online() -> None:
    engine = config.attributes["engine"]
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
