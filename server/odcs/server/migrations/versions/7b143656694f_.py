"""Add parent_pungi_compose_ids.

Revision ID: 7b143656694f
Revises: 512890e6864d
Create Date: 2020-08-17 08:07:45.861953

"""

# revision identifiers, used by Alembic.
revision = "7b143656694f"
down_revision = "512890e6864d"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "composes", sa.Column("parent_pungi_compose_ids", sa.String(), nullable=True)
    )


def downgrade():
    op.drop_column("composes", "parent_pungi_compose_ids")
