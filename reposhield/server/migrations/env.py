import os
from alembic import context
from sqlalchemy import create_engine, pool
from reposhield.server.schema_v1 import metadata

config = context.config
url = config.attributes.get("database_url") or os.environ.get("REPOSHIELD_DATABASE_URL")
if not url or not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("Set REPOSHIELD_DATABASE_URL to a postgresql+psycopg URL")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
