from alembic import context
from app.db import Base, engine
from app import models
from app.v2 import models as v2_models

config = context.config

if context.is_offline_mode():
    from app.config import settings
    context.configure(url=settings.database_url, target_metadata=Base.metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
