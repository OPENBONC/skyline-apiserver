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
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, insert, literal, or_, select, update

from skyline_apiserver.types import Fn, constants

from .base import DB, inject_db
from .models import RevokedToken, Settings, SnapshotPolicy, SnapshotPolicyVolume, AuditLog, AuditLogDetail, RevokedToken, Settings

MAX_QUERY_LIMIT = 10000
from .models import QuotaOrder, RevokedToken, Settings, SnapshotPolicy, SnapshotPolicyVolume
from .models import ManagedCluster


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
        select([Settings.c.key, Settings.c.value])
        .where(Settings.c.key == key)
        .with_for_update()
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
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
) -> Any:
    now = datetime.now().isoformat(timespec="microseconds")
    db = DB.get()
    async with db.transaction():
        await db.execute(
            insert(SnapshotPolicy),
            {
                "id": policy_id,
                "name": name,
                "repeat_days": repeat_days,
                "create_times": create_times,
                "user_id": user_id,
                "user_name": user_name,
                "project_id": project_id,
                "project_name": project_name,
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
    now = datetime.now().isoformat(timespec="microseconds")
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


async def create_audit_log(
    main_values: Dict[str, Any],
    detail_values: Dict[str, Any],
    now_ms: int,
) -> None:
    main_values["created_at"] = now_ms
    main_values["updated_at"] = now_ms
    detail_values["created_at"] = now_ms
    detail_values["updated_at"] = now_ms
    db = DB.get()
    async with db.transaction():
        await db.execute(insert(AuditLog), main_values)
        await db.execute(insert(AuditLogDetail), detail_values)


@check_db_connected
async def update_audit_log(
    log_id: str,
    domain_id: str,
    now_ms: int,
    request_result: Optional[str] = None,
    http_code: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    domain_name: Optional[str] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> str:
    db = DB.get()
    async with db.transaction():
        main_query = select(
            [
                AuditLog.c.id,
                AuditLog.c.request_result,
                AuditLog.c.domain_name,
                AuditLog.c.user_id,
                AuditLog.c.user_name,
            ]
        ).where(AuditLog.c.id == log_id, AuditLog.c.domain_id == domain_id)
        main_row = await db.fetch_one(main_query)

        allow_bare_update = False
        if main_row is None:
            detail_query = select([AuditLogDetail.c.request_path]).where(
                AuditLogDetail.c.log_id == log_id
            )
            detail_row = await db.fetch_one(detail_query)
            if detail_row and detail_row["request_path"]:
                path = detail_row["request_path"].lower()
                if "login" in path or "logout" in path:
                    bare_query = select(
                        [
                            AuditLog.c.id,
                            AuditLog.c.request_result,
                            AuditLog.c.domain_name,
                            AuditLog.c.user_id,
                            AuditLog.c.user_name,
                        ]
                    ).where(AuditLog.c.id == log_id)
                    main_row = await db.fetch_one(bare_query)
                    allow_bare_update = True

        if main_row is None:
            return "not_found"

        changed_main = request_result is not None and request_result != main_row["request_result"]
        main_updates: Dict[str, Any] = {}
        if domain_name is not None and domain_name != main_row["domain_name"]:
            main_updates["domain_name"] = domain_name
        if user_id is not None and user_id != main_row["user_id"]:
            main_updates["user_id"] = user_id
        if user_name is not None and user_name != main_row["user_name"]:
            main_updates["user_name"] = user_name
        if main_updates:
            changed_main = True

        changed_detail = False
        if http_code is not None or error_code is not None or error_message is not None:
            detail_query = select([AuditLogDetail]).where(AuditLogDetail.c.log_id == log_id)
            detail_row = await db.fetch_one(detail_query)
            if detail_row is not None:
                changed_detail = (
                    (http_code is not None and http_code != detail_row["http_code"])
                    or (error_code is not None and error_code != detail_row["error_code"])
                    or (
                        error_message is not None and error_message != detail_row["error_message"]
                    )
                )

        if changed_main:
            main_update_query = update(AuditLog)
            if allow_bare_update:
                main_update_query = main_update_query.where(AuditLog.c.id == log_id)
            else:
                main_update_query = main_update_query.where(
                    AuditLog.c.id == log_id, AuditLog.c.domain_id == domain_id
                )
            update_values: Dict[str, Any] = {"updated_at": now_ms}
            if request_result is not None:
                update_values["request_result"] = request_result
            update_values.update(main_updates)
            await db.execute(main_update_query, update_values)

        if changed_detail:
            detail_values: Dict[str, Any] = {"updated_at": now_ms}
            if http_code is not None:
                detail_values["http_code"] = http_code
            if error_code is not None:
                detail_values["error_code"] = error_code
            if error_message is not None:
                detail_values["error_message"] = error_message
            await db.execute(
                update(AuditLogDetail).where(AuditLogDetail.c.log_id == log_id),
                detail_values,
            )

        if changed_main or changed_detail:
            return "updated"
        return "no_change"


@check_db_connected
async def get_audit_log(log_id: str, domain_name: str) -> Any:
    query = select([AuditLog]).where(AuditLog.c.id == log_id, AuditLog.c.domain_name == domain_name)
    db = DB.get()
    async with db.transaction():
        return await db.fetch_one(query)


@check_db_connected
async def get_audit_log_detail(log_id: str) -> Any:
    query = select([AuditLogDetail]).where(AuditLogDetail.c.log_id == log_id)
    db = DB.get()
    async with db.transaction():
        return await db.fetch_one(query)


@check_db_connected
async def list_audit_logs(
    domain_name: str,
    page: int = 1,
    size: int = 10,
    project_id: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    operator_name: Optional[str] = None,
    module: Optional[str] = None,
    action: Optional[str] = None,
    request_result: Optional[str] = None,
    target: Optional[str] = None,
) -> Tuple[int, List[Any]]:
    conditions = [AuditLog.c.domain_name == domain_name]
    if project_id:
        conditions.append(AuditLog.c.project_id == project_id)
    if start_time is not None:
        conditions.append(AuditLog.c.created_at >= start_time)
    if end_time is not None:
        conditions.append(AuditLog.c.created_at <= end_time)
    if operator_name:
        conditions.append(func.lower(AuditLog.c.user_name).like(f"%{operator_name.lower()}%"))
    if module:
        conditions.append(AuditLog.c.module == module)
    if action:
        conditions.append(AuditLog.c.action == action)
    if request_result:
        conditions.append(AuditLog.c.request_result == request_result)
    if target:
        escaped = target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").lower()
        conditions.append(
            or_(
                func.lower(AuditLog.c.targets).like(f'%"id": "%{escaped}%"%', escape="\\"),
                func.lower(AuditLog.c.targets).like(f'%"name": "%{escaped}%"%', escape="\\"),
            )
        )

    db = DB.get()
    async with db.transaction():
        count_query = select([func.count().label("total")]).select_from(
            select([literal(1)])
            .select_from(AuditLog)
            .where(*conditions)
            .limit(MAX_QUERY_LIMIT + 1)
            .subquery()
        )
        count_row = await db.fetch_one(count_query)
        total = min(int(count_row["total"]), MAX_QUERY_LIMIT) if count_row else 0

        offset = (page - 1) * size
        rows: List[Any] = []
        if offset < MAX_QUERY_LIMIT:
            limit = min(size, MAX_QUERY_LIMIT - offset)
            query = (
                select([AuditLog])
                .where(*conditions)
                .order_by(AuditLog.c.created_at.desc(), AuditLog.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = await db.fetch_all(query)

    return total, rows


@check_db_connected
async def list_quota_orders(
    user_id: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Any:
    count_label = "count"
    count_query = select([func.count(QuotaOrder.c.id).label(count_label)])
    query = select([QuotaOrder]).order_by(QuotaOrder.c.created_at.desc())
    if user_id:
        count_query = count_query.where(QuotaOrder.c.user_id == user_id)
        query = query.where(QuotaOrder.c.user_id == user_id)
    if statuses:
        count_query = count_query.where(QuotaOrder.c.status.in_(statuses))
        query = query.where(QuotaOrder.c.status.in_(statuses))
    if search:
        count_query = count_query.where(QuotaOrder.c.id == search)
        query = query.where(QuotaOrder.c.id == search)
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
async def get_quota_order(order_id: str) -> Any:
    query = select([QuotaOrder]).where(QuotaOrder.c.id == order_id)
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_one(query)

    return result


@check_db_connected
async def create_quota_order(
    order_id: str,
    title: str,
    quota: Any,
    user_id: str,
    user_name: str,
    project_id: str,
    project_name: Optional[str],
) -> Any:
    now = datetime.now().isoformat(timespec="microseconds")
    db = DB.get()
    async with db.transaction():
        result = await db.execute(
            insert(QuotaOrder),
            {
                "id": order_id,
                "title": title,
                "quota": quota,
                "status": constants.QUOTA_ORDER_STATUS_PENDING,
                "user_id": user_id,
                "user_name": user_name,
                "project_id": project_id,
                "project_name": project_name,
                "created_at": now,
                "ended_at": None,
            },
        )

    return result


@check_db_connected
async def update_quota_order_status(order_id: str, status: str) -> Any:
    now = datetime.now().isoformat(timespec="microseconds")
    db = DB.get()
    async with db.transaction():
        result = await db.execute(
            update(QuotaOrder)
            .where(QuotaOrder.c.id == order_id)
            .values(status=status, ended_at=now),
        )

    return result


@check_db_connected
async def list_managed_clusters(
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Any:
    count_label = "count"
    count_query = select([func.count(ManagedCluster.c.id).label(count_label)])
    query = select([ManagedCluster]).order_by(ManagedCluster.c.created_at.desc())
    if search:
        count_query = count_query.where(
            or_(
                ManagedCluster.c.id == search,
                ManagedCluster.c.name == search,
                ManagedCluster.c.address == search,
            )
        )
        query = query.where(
            or_(
                ManagedCluster.c.id == search,
                ManagedCluster.c.name == search,
                ManagedCluster.c.address == search,
            )
        )
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
async def get_managed_cluster(cluster_id: str) -> Any:
    query = select([ManagedCluster]).where(ManagedCluster.c.id == cluster_id)
    db = DB.get()
    async with db.transaction():
        result = await db.fetch_one(query)

    return result


@check_db_connected
async def create_managed_cluster(
    cluster_id: str,
    name: str,
    address: str,
    config_yaml: str,
) -> Any:
    now = datetime.now().isoformat(timespec="microseconds")
    db = DB.get()
    async with db.transaction():
        result = await db.execute(
            insert(ManagedCluster),
            {
                "id": cluster_id,
                "name": name,
                "address": address,
                "config_yaml": config_yaml,
                "status": constants.CLUSTER_STATUS_UNASSIGNED,
                "user_id": None,
                "user_name": None,
                "project_id": None,
                "project_name": None,
                "created_at": now,
                "updated_at": now,
            },
        )

    return result


@check_db_connected
async def update_managed_cluster_status(
    cluster_id: str,
    status: str,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
) -> Any:
    now = datetime.now().isoformat(timespec="microseconds")
    values: Dict[str, Any] = {
        "status": status,
        "updated_at": now,
    }
    if user_id is not None:
        values.update(
            {
                "user_id": user_id,
                "user_name": user_name,
                "project_id": project_id,
                "project_name": project_name,
            }
        )
    elif status == constants.CLUSTER_STATUS_UNASSIGNED:
        values.update(
            {
                "user_id": None,
                "user_name": None,
                "project_id": None,
                "project_name": None,
            }
        )
    db = DB.get()
    async with db.transaction():
        result = await db.execute(
            update(ManagedCluster)
            .where(ManagedCluster.c.id == cluster_id)
            .values(values),
        )

    return result


@check_db_connected
async def delete_managed_cluster(cluster_id: str) -> Any:
    db = DB.get()
    async with db.transaction():
        result = await db.execute(
            delete(ManagedCluster).where(ManagedCluster.c.id == cluster_id),
        )

    return result
