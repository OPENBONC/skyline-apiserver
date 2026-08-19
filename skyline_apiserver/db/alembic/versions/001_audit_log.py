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

"""add audit log tables

Revision ID: 001
Revises: 000
Create Date: 2026-08-18 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "001"
down_revision = "000"
branch_labels = None
depends_on = None

LONGTEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")
MYSQL_TIMESTAMP = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("domain_id", sa.String(length=64), nullable=False),
        sa.Column("domain_name", sa.String(length=255), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("project_name", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("module", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=True),
        sa.Column("targets", LONGTEXT, nullable=True),
        sa.Column("target_names", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("request_result", sa.String(length=128), nullable=True),
        sa.Column("created_at", MYSQL_TIMESTAMP, nullable=False),
        sa.Column("updated_at", MYSQL_TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_logs_domain_created_id",
        "audit_log",
        ["domain_id", "created_at", "id"],
    )
    op.create_index(
        "idx_logs_domain_project_created_id",
        "audit_log",
        ["domain_id", "project_id", "created_at", "id"],
    )
    op.create_index(
        "idx_logs_domain_module_created_id",
        "audit_log",
        ["domain_id", "module", "created_at", "id"],
    )
    op.create_index(
        "idx_logs_domain_action_created_id",
        "audit_log",
        ["domain_id", "action", "created_at", "id"],
    )
    op.create_index(
        "idx_logs_domain_result_created_id",
        "audit_log",
        ["domain_id", "request_result", "created_at", "id"],
    )

    op.create_table(
        "audit_log_detail",
        sa.Column("log_id", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("request_method", sa.String(length=16), nullable=True),
        sa.Column("request_path", sa.String(length=2048), nullable=True),
        sa.Column("request_body", LONGTEXT, nullable=True),
        sa.Column("http_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", LONGTEXT, nullable=True),
        sa.Column("created_at", MYSQL_TIMESTAMP, nullable=False),
        sa.Column("updated_at", MYSQL_TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("log_id"),
    )


def downgrade() -> None:
    op.drop_table("audit_log_detail")
    op.drop_index("idx_logs_domain_result_created_id", table_name="audit_log")
    op.drop_index("idx_logs_domain_action_created_id", table_name="audit_log")
    op.drop_index("idx_logs_domain_module_created_id", table_name="audit_log")
    op.drop_index("idx_logs_domain_project_created_id", table_name="audit_log")
    op.drop_index("idx_logs_domain_created_id", table_name="audit_log")
    op.drop_table("audit_log")
