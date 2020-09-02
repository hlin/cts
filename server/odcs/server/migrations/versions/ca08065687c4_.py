"""Add scratch_build_tasks field.

Revision ID: ca08065687c4
Revises: 7b143656694f
Create Date: 2020-09-03 11:20:54.035095

"""

# revision identifiers, used by Alembic.
revision = "ca08065687c4"
down_revision = "7b143656694f"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "composes", sa.Column("scratch_build_tasks", sa.String(), nullable=True)
    )


def downgrade():
    op.drop_column("composes", "scratch_build_tasks")
