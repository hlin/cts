"""Add Compose.scratch_modules

Revision ID: 512890e6864d
Revises: 812f2745248f
Create Date: 2020-07-31 22:40:13.138130

"""

# revision identifiers, used by Alembic.
revision = "512890e6864d"
down_revision = "812f2745248f"

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("composes", sa.Column("scratch_modules", sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("composes", "scratch_modules")
    # ### end Alembic commands ###
