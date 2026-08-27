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

"""add last_scheduled_at to snapshot_policy_volume

Revision ID: 009
Revises: 008
Create Date: 2026-08-28 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("snapshot_policy_volume") as batch_op:
        batch_op.add_column(
            sa.Column("last_scheduled_at", sa.BigInteger(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("snapshot_policy_volume") as batch_op:
        batch_op.drop_column("last_scheduled_at")
