"""Add pungi_config_dump column.

Revision ID: 82172e6a3154
Revises: cd0781bbdab1
Create Date: 2020-02-05 13:20:59.014127

"""

# revision identifiers, used by Alembic.
revision = "82172e6a3154"
down_revision = "cd0781bbdab1"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "composes", sa.Column("pungi_config_dump", sa.String(), nullable=True)
    )


def downgrade():
    op.drop_column("composes", "pungi_config_dump")
