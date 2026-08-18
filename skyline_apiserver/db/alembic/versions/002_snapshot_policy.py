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

"""snapshot policy

Revision ID: 001
Revises: 000
Create Date: 2023-01-01 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_policy",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("repeat_days", sa.JSON(), nullable=False),
        sa.Column("create_times", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "snapshot_policy_volume",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("volume_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_snapshot_policy_volume_policy_id"),
        "snapshot_policy_volume",
        ["policy_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_snapshot_policy_volume_volume_id"),
        "snapshot_policy_volume",
        ["volume_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_snapshot_policy_volume_volume_id"),
        table_name="snapshot_policy_volume",
    )
    op.drop_index(
        op.f("ix_snapshot_policy_volume_policy_id"),
        table_name="snapshot_policy_volume",
    )
    op.drop_table("snapshot_policy_volume")
    op.drop_table("snapshot_policy")
