from create_database import create_database,create_user
from run_alembic_commands import run_alembic_commands

create_database()
run_alembic_commands()
create_user()