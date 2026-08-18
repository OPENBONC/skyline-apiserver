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

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table

METADATA = MetaData()


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
