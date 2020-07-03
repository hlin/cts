"""Add index on Compose.source_type and Compose.state

Revision ID: c370b90de998
Revises: f24a36cc8a16
Create Date: 2017-09-21 11:47:09.381048

"""

# revision identifiers, used by Alembic.
revision = "c370b90de998"
down_revision = "f24a36cc8a16"

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index("idx_source_type__state", "composes", ["source_type", "state"])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("idx_source_type__state", table_name="composes")
    # ### end Alembic commands ###
