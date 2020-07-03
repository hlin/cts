"""Add compose_type, label and pungi_compose_id columns.

Revision ID: cd0781bbdab1
Revises: de0a86d7de49
Create Date: 2020-01-09 11:14:30.378081

"""

# revision identifiers, used by Alembic.
revision = "cd0781bbdab1"
down_revision = "de0a86d7de49"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("composes", sa.Column("compose_type", sa.String(), nullable=True))
    op.add_column("composes", sa.Column("label", sa.String(), nullable=True))
    op.add_column("composes", sa.Column("pungi_compose_id", sa.String(), nullable=True))


def downgrade():
    op.drop_column("composes", "pungi_compose_id")
    op.drop_column("composes", "label")
    op.drop_column("composes", "compose_type")
