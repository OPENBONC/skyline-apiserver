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

"""add creator info to snapshot policy

Revision ID: 004
Revises: 003
Create Date: 2026-08-20 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snapshot_policy",
        sa.Column("user_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "snapshot_policy",
        sa.Column("user_name", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "snapshot_policy",
        sa.Column("project_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "snapshot_policy",
        sa.Column("project_name", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snapshot_policy", "project_name")
    op.drop_column("snapshot_policy", "project_id")
    op.drop_column("snapshot_policy", "user_name")
    op.drop_column("snapshot_policy", "user_id")
