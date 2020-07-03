"""Add target_dir column.

Revision ID: 812f2745248f
Revises: a855c39e2a0f
Create Date: 2020-03-13 13:28:24.381076

"""

# revision identifiers, used by Alembic.
revision = "812f2745248f"
down_revision = "a855c39e2a0f"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("composes", sa.Column("target_dir", sa.String(), nullable=True))


def downgrade():
    op.drop_column("composes", "target_dir")
