"""Add composes.respin_of.

Revision ID: b00f3b6efaed
Revises: c1b7e84ff39b
Create Date: 2020-11-19 10:25:09.861938

"""

# revision identifiers, used by Alembic.
revision = "b00f3b6efaed"
down_revision = "c1b7e84ff39b"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("composes", sa.Column("respin_of", sa.String(), nullable=True))


def downgrade():
    op.drop_column("composes", "respin_of")
