"""Add Compose.modules.

Revision ID: c1b7e84ff39b
Revises: ca08065687c4
Create Date: 2020-11-19 08:37:34.961983

"""

# revision identifiers, used by Alembic.
revision = "c1b7e84ff39b"
down_revision = "ca08065687c4"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("composes", sa.Column("modules", sa.String(), nullable=True))


def downgrade():
    op.drop_column("composes", "modules")
