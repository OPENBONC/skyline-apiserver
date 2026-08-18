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

import time
import uuid
from functools import wraps
from typing import Any, List, Optional

from sqlalchemy import delete, func, insert, select, update

from skyline_apiserver.types import Fn

from .base import DB, inject_db
from .models import RevokedToken, Settings, SnapshotPolicy, SnapshotPolicyVolume


def check_db_connected(fn: Fn) -> Any:
    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        await inject_db()
        db = DB.get()
        assert db is not None, "Database is not connected."
        return await fn(*args, **kwargs)

    return wrapper


@check_db_connected
async def check_token(token_id: str) -> bool:
    count_label = "revoked_count"
    query = (
        select([func.count(RevokedToken.c.uuid).label(count_label)])
        .select_from(RevokedToken)
        .where(RevokedToken.c.uuid == token_id)
    )
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_one(query)

    count = getattr(result, count_label, 0)
    return count > 0


@check_db_connected
async def revoke_token(token_id: str, expire: int) -> Any:
    query = insert(RevokedToken)
    db = DB.get()
    async with db.transaction():
        result = await db.execute(query, {"uuid": token_id, "expire": expire})

    return result


@check_db_connected
async def purge_revoked_token() -> Any:
    now = int(time.time()) - 1
    query = delete(RevokedToken).where(RevokedToken.c.expire < now)
    db = DB.get()
    async with db.transaction():
        result = await db.execute(query)

    return result


@check_db_connected
async def list_settings() -> Any:
    query = select([Settings])
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_all(query)

    return result


@check_db_connected
async def get_setting(key: str) -> Any:
    query = select([Settings]).where(Settings.c.key == key)
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_one(query)

    return result


@check_db_connected
async def update_setting(key: str, value: Any) -> Any:
    get_query = (
        select([Settings.c.key, Settings.c.value]).where(Settings.c.key == key).with_for_update()
    )
    db = DB.get()
    async with db.transaction():
        is_exist = await db.fetch_one(get_query)
        if is_exist is None:
            query = insert(Settings)
            await db.execute(query, {"key": key, "value": value})
        else:
            query = update(Settings).where(Settings.c.key == key)
            await db.execute(query, {"value": value})
        result = await db.fetch_one(get_query)

    return result


@check_db_connected
async def delete_setting(key: str) -> Any:
    query = delete(Settings).where(Settings.c.key == key)
    db = DB.get()
    async with db.transaction():
        result = await db.execute(query)

    return result


@check_db_connected
async def list_snapshot_policies(
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Any:
    count_label = "count"
    count_query = select([func.count(SnapshotPolicy.c.id).label(count_label)])
    query = (
        select(
            [
                SnapshotPolicy,
                func.count(SnapshotPolicyVolume.c.id).label("volume_count"),
            ],
        )
        .select_from(
            SnapshotPolicy.outerjoin(
                SnapshotPolicyVolume,
                SnapshotPolicy.c.id == SnapshotPolicyVolume.c.policy_id,
            ),
        )
        .group_by(SnapshotPolicy.c.id)
        .order_by(SnapshotPolicy.c.created_at.desc())
    )
    if search:
        count_query = count_query.where(SnapshotPolicy.c.id == search)
        query = query.where(SnapshotPolicy.c.id == search)
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    db = DB.get()
    async with db.transaction():
        count = await db.fetch_val(count_query)
        result = await db.fetch_all(query)

    return result, count or 0


@check_db_connected
async def get_snapshot_policy(policy_id: str) -> Any:
    query = select([SnapshotPolicy]).where(SnapshotPolicy.c.id == policy_id)
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_one(query)

    return result


@check_db_connected
async def create_snapshot_policy(
    policy_id: str,
    name: Optional[str],
    repeat_days: List[int],
    create_times: List[int],
    volume_ids: List[str],
) -> Any:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    db = DB.get()
    async with db.transaction():
        await db.execute(
            insert(SnapshotPolicy),
            {
                "id": policy_id,
                "name": name,
                "repeat_days": repeat_days,
                "create_times": create_times,
                "created_at": now,
                "updated_at": now,
            },
        )
        for volume_id in volume_ids:
            await db.execute(
                insert(SnapshotPolicyVolume),
                {
                    "id": str(uuid.uuid4()),
                    "policy_id": policy_id,
                    "volume_id": volume_id,
                    "created_at": now,
                },
            )

    return policy_id


@check_db_connected
async def update_snapshot_policy(
    policy_id: str,
    name: Optional[str],
    repeat_days: List[int],
    create_times: List[int],
    volume_ids: List[str],
) -> Any:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    db = DB.get()
    async with db.transaction():
        await db.execute(
            update(SnapshotPolicy)
            .where(SnapshotPolicy.c.id == policy_id)
            .values(
                name=name,
                repeat_days=repeat_days,
                create_times=create_times,
                updated_at=now,
            ),
        )
        await db.execute(
            delete(SnapshotPolicyVolume).where(
                SnapshotPolicyVolume.c.policy_id == policy_id,
            ),
        )
        for volume_id in volume_ids:
            await db.execute(
                insert(SnapshotPolicyVolume),
                {
                    "id": str(uuid.uuid4()),
                    "policy_id": policy_id,
                    "volume_id": volume_id,
                    "created_at": now,
                },
            )

    return policy_id


@check_db_connected
async def delete_snapshot_policy(policy_id: str) -> Any:
    db = DB.get()
    async with db.transaction():
        await db.execute(delete(SnapshotPolicy).where(SnapshotPolicy.c.id == policy_id))
        await db.execute(
            delete(SnapshotPolicyVolume).where(
                SnapshotPolicyVolume.c.policy_id == policy_id,
            ),
        )

    return policy_id


@check_db_connected
async def delete_snapshot_policies(policy_ids: List[str]) -> Any:
    db = DB.get()
    async with db.transaction():
        await db.execute(
            delete(SnapshotPolicy).where(SnapshotPolicy.c.id.in_(policy_ids)),
        )
        await db.execute(
            delete(SnapshotPolicyVolume).where(
                SnapshotPolicyVolume.c.policy_id.in_(policy_ids),
            ),
        )

    return policy_ids


@check_db_connected
async def list_policy_volumes(
    policy_id: Optional[str] = None,
    volume_id: Optional[str] = None,
) -> Any:
    query = select([SnapshotPolicyVolume])
    if policy_id:
        query = query.where(SnapshotPolicyVolume.c.policy_id == policy_id)
    if volume_id:
        query = query.where(SnapshotPolicyVolume.c.volume_id == volume_id)
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_all(query)

    return result


@check_db_connected
async def get_volume_policy(volume_id: str) -> Any:
    query = select([SnapshotPolicyVolume]).where(
        SnapshotPolicyVolume.c.volume_id == volume_id,
    )
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_one(query)

    return result
