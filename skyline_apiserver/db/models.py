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

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Column, Index, Integer, MetaData, String, Table, Text
from sqlalchemy.dialects import mysql

METADATA = MetaData()

LONGTEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")
MYSQL_TIMESTAMP = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


RevokedToken = Table(
    "revoked_token",
    METADATA,
    Column("uuid", String(length=128), nullable=False, index=True, unique=False),
    Column("expire", Integer, nullable=False),
)

Settings = Table(
    "settings",
    METADATA,
    Column("key", String(length=128), nullable=False, index=True, unique=True),
    Column("value", JSON, nullable=True),
)

SnapshotPolicy = Table(
    "snapshot_policy",
    METADATA,
    Column("id", String(length=36), primary_key=True, nullable=False),
    Column("name", String(length=255), nullable=True),
    Column("repeat_days", JSON, nullable=False),
    Column("create_times", JSON, nullable=False),
    Column("user_id", String(length=64), nullable=True),
    Column("user_name", String(length=64), nullable=True),
    Column("project_id", String(length=64), nullable=True),
    Column("project_name", String(length=64), nullable=True),
    Column("created_at", String(length=32), nullable=False),
    Column("updated_at", String(length=32), nullable=False),
)

SnapshotPolicyVolume = Table(
    "snapshot_policy_volume",
    METADATA,
    Column("id", String(length=36), primary_key=True, nullable=False),
    Column("policy_id", String(length=36), nullable=False, index=True),
    Column("volume_id", String(length=36), nullable=False, index=True, unique=True),
    Column("created_at", String(length=32), nullable=False),
)

AuditLog = Table(
    "audit_log",
    METADATA,
    Column("id", String(length=32), nullable=False, primary_key=True),
    Column("domain_id", String(length=64), nullable=False),
    Column("domain_name", String(length=255), nullable=True),
    Column("project_id", String(length=64), nullable=True),
    Column("project_name", String(length=255), nullable=True),
    Column("user_id", String(length=64), nullable=False),
    Column("user_name", String(length=255), nullable=True),
    Column("module", String(length=128), nullable=True),
    Column("action", String(length=255), nullable=True),
    Column("targets", LONGTEXT, nullable=True),
    Column("target_names", Text, nullable=True),
    Column("source_ip", String(length=45), nullable=True),
    Column("request_result", String(length=128), nullable=True),
    Column("created_at", MYSQL_TIMESTAMP, nullable=False),
    Column("updated_at", MYSQL_TIMESTAMP, nullable=False),
)

AuditLogDetail = Table(
    "audit_log_detail",
    METADATA,
    Column("log_id", String(length=32), nullable=False, primary_key=True),
    Column("trace_id", String(length=128), nullable=True),
    Column("request_method", String(length=16), nullable=True),
    Column("request_path", String(length=2048), nullable=True),
    Column("request_body", LONGTEXT, nullable=True),
    Column("http_code", Integer, nullable=True),
    Column("error_code", String(length=128), nullable=True),
    Column("error_message", LONGTEXT, nullable=True),
    Column("created_at", MYSQL_TIMESTAMP, nullable=False),
    Column("updated_at", MYSQL_TIMESTAMP, nullable=False),
)

Index(
    "idx_logs_domain_created_id",
    AuditLog.c.domain_id,
    AuditLog.c.created_at,
    AuditLog.c.id,
)
Index(
    "idx_logs_domain_project_created_id",
    AuditLog.c.domain_id,
    AuditLog.c.project_id,
    AuditLog.c.created_at,
    AuditLog.c.id,
)
Index(
    "idx_logs_domain_module_created_id",
    AuditLog.c.domain_id,
    AuditLog.c.module,
    AuditLog.c.created_at,
    AuditLog.c.id,
)
Index(
    "idx_logs_domain_action_created_id",
    AuditLog.c.domain_id,
    AuditLog.c.action,
    AuditLog.c.created_at,
    AuditLog.c.id,
)
Index(
    "idx_logs_domain_result_created_id",
    AuditLog.c.domain_id,
    AuditLog.c.request_result,
    AuditLog.c.created_at,
    AuditLog.c.id,
)
QuotaOrder = Table(
    "quota_order",
    METADATA,
    Column("id", String(length=36), primary_key=True, nullable=False),
    Column("title", String(length=60), nullable=False),
    Column("quota", JSON, nullable=False),
    Column("status", String(length=16), nullable=False),
    Column("user_id", String(length=64), nullable=False, index=True),
    Column("user_name", String(length=64), nullable=False),
    Column("project_id", String(length=64), nullable=False),
    Column("project_name", String(length=64), nullable=True),
    Column("created_at", String(length=32), nullable=False),
    Column("ended_at", String(length=32), nullable=True),
)

ManagedCluster = Table(
    "managed_cluster",
    METADATA,
    Column("id", String(length=36), primary_key=True, nullable=False),
    Column("name", String(length=255), nullable=False),
    Column("address", String(length=255), nullable=False),
    Column("config_yaml", LONGTEXT, nullable=False),
    Column("status", String(length=16), nullable=False),
    Column("user_id", String(length=64), nullable=True, index=True),
    Column("user_name", String(length=64), nullable=True),
    Column("project_id", String(length=64), nullable=True),
    Column("project_name", String(length=64), nullable=True),
    Column("created_at", String(length=32), nullable=False),
    Column("updated_at", String(length=32), nullable=False),
)
