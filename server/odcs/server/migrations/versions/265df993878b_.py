"""Add result_repo_name

Revision ID: 265df993878b
Revises: b75ad2afc207
Create Date: 2017-11-29 13:58:29.213911

"""

# revision identifiers, used by Alembic.
revision = '265df993878b'
down_revision = 'b75ad2afc207'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('composes', sa.Column('result_repo_name', sa.String(), nullable=True))


def downgrade():
    op.drop_column('composes', 'result_repo_name')
