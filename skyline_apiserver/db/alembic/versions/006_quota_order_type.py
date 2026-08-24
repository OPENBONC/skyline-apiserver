# Copyright 2021 99cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""add type to quota order

Revision ID: 006
Revises: 005
Create Date: 2026-08-20 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("quota_order") as batch_op:
        batch_op.add_column(
            sa.Column("type", sa.String(length=16), server_default="quota", nullable=False)
        )
        batch_op.alter_column("quota", existing_type=sa.JSON(), nullable=True)
        batch_op.add_column(sa.Column("cluster_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("quota_order") as batch_op:
        batch_op.drop_column("cluster_id")
        batch_op.alter_column("quota", existing_type=sa.JSON(), nullable=False)
        batch_op.drop_column("type")