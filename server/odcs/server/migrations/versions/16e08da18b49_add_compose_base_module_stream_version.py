"""Add compose base module stream version

Revision ID: 16e08da18b49
Revises: 59baece89746
Create Date: 2021-02-15 09:50:58.470959

"""

# revision identifiers, used by Alembic.
revision = "16e08da18b49"
down_revision = "59baece89746"

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "composes",
        sa.Column("base_module_br_stream_version_gte", sa.Integer(), nullable=True),
    )
    op.add_column(
        "composes",
        sa.Column("base_module_br_stream_version_lte", sa.Integer(), nullable=True),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("composes", "base_module_br_stream_version_lte")
    op.drop_column("composes", "base_module_br_stream_version_gte")
    # ### end Alembic commands ###
