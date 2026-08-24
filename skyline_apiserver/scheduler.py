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

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from skyline_apiserver.client import utils
from skyline_apiserver.client.openstack import cinder
from skyline_apiserver.config import CONF
from skyline_apiserver.db import api as db_api
from skyline_apiserver.log import LOG

AUTO_SNAPSHOT_METADATA_KEY = "skyline_auto_snapshot"
SNAPSHOT_POLICY_METADATA_KEY = "skyline_snapshot_policy_id"
AUTO_SNAPSHOT_NAME_PREFIX = "auto-snapshot"


async def run_snapshot_scheduler() -> None:
    """Periodically scan snapshot policies and create snapshots if needed."""
    if not CONF.default.snapshot_scheduler_enabled:
        LOG.info("Scheduled snapshot scheduler is disabled.")
        return
    LOG.info("Scheduled snapshot scheduler started.")
    while True:
        try:
            await _scheduler_tick()
        except asyncio.CancelledError:
            LOG.info("Scheduled snapshot scheduler stopped.")
            raise
        except Exception as e:
            LOG.error(f"Failed to run scheduled snapshot scheduler tick: {e}")
        await asyncio.sleep(CONF.default.snapshot_scheduler_interval)


async def _scheduler_tick() -> None:
    now = datetime.now()
    weekday = now.isoweekday()
    hour = now.hour

    policy_rows, _ = await db_api.list_snapshot_policies()
    if not policy_rows:
        return
    volume_rows = await db_api.list_policy_volumes()

    policies: Dict[str, Dict[str, Any]] = {
        policy["id"]: {
            "repeat_days": policy["repeat_days"],
            "create_times": policy["create_times"],
            "volumes": [],
        }
        for policy in policy_rows
    }
    for row in volume_rows:
        policy_id = row["policy_id"]
        if policy_id in policies:
            policies[policy_id]["volumes"].append(row["volume_id"])

    for policy_id, policy in policies.items():
        try:
            if weekday not in policy["repeat_days"] or hour not in policy["create_times"]:
                continue
            for volume_id in policy["volumes"]:
                try:
                    await _process_volume(policy_id, volume_id, now)
                except Exception as e:
                    LOG.error(
                        f"Failed to create scheduled snapshot for volume {volume_id} "
                        f"with policy {policy_id}: {e}",
                    )
        except Exception as e:
            LOG.error(f"Failed to process snapshot policy {policy_id}: {e}")


async def _process_volume(policy_id: str, volume_id: str, now: datetime) -> None:
    policy = await db_api.get_snapshot_policy(policy_id)
    if policy is None:
        LOG.error(f"Snapshot policy {policy_id} no longer exists, skip.")
        return
    session = utils.get_system_session()
    project_session = utils.get_system_session_by_project(policy["project_id"])
    region = CONF.openstack.default_region

    snapshots = await cinder.list_volume_snapshots_by_session(
        session=session,
        region=region,
        search_opts={"volume_id": volume_id, "all_tenants": True},
    )
    policy_snapshots = [
        snapshot
        for snapshot in snapshots
        if (snapshot.metadata or {}).get(SNAPSHOT_POLICY_METADATA_KEY) == policy_id
    ]

    if _created_in_current_slot(policy_snapshots, now):
        LOG.debug(
            f"Snapshot for volume {volume_id} already created in this hour, skip.",
        )
        return

    # If the previous snapshot took longer than the interval (one hour at least),
    # skip this time point automatically.
    if _is_snapshot_still_creating(policy_snapshots):
        LOG.info(
            f"Snapshot for volume {volume_id} is still being created, skip this time point.",
        )
        return

    await _enforce_quota(session, region, volume_id, policy_snapshots)

    name = _generate_snapshot_name(volume_id, now)
    metadata = {
        AUTO_SNAPSHOT_METADATA_KEY: "true",
        SNAPSHOT_POLICY_METADATA_KEY: policy_id,
    }
    LOG.info(
        f"Creating scheduled snapshot {name} for volume {volume_id} "
        f"by policy {policy_id} in project {policy['project_id']}.",
    )
    await cinder.create_volume_snapshot(
        project_session,
        region,
        volume_id,
        name=name,
        metadata=metadata,
    )


async def _enforce_quota(
    session: Any,
    region: str,
    volume_id: str,
    policy_snapshots: List[Any],
) -> None:
    """Keep auto snapshots within the quota by deleting the oldest ones."""
    quota = CONF.default.auto_snapshot_quota
    if len(policy_snapshots) < quota:
        return
    number_to_delete = len(policy_snapshots) - quota + 1
    ordered = sorted(policy_snapshots, key=lambda s: _to_local_dt(s.created_at))
    target = [snapshot for snapshot in ordered if snapshot.status != "creating"][
        :number_to_delete
    ]
    for snapshot in target:
        try:
            LOG.info(
                f"Auto snapshot {snapshot.id} of volume {volume_id} exceeds quota, "
                f"deleting it.",
            )
            await cinder.delete_volume_snapshot(session, region, snapshot.id)
        except Exception as e:
            LOG.error(f"Failed to delete snapshot {snapshot.id}: {e}")


def _created_in_current_slot(policy_snapshots: List[Any], now: datetime) -> bool:
    """Whether the policy has already created a snapshot during this hour."""
    for snapshot in policy_snapshots:
        created_at = _to_local_dt(snapshot.created_at)
        if created_at.date() == now.date() and created_at.hour == now.hour:
            return True
    return False


def _is_snapshot_still_creating(policy_snapshots: List[Any]) -> bool:
    if not policy_snapshots:
        return False
    ordered = sorted(policy_snapshots, key=lambda s: _to_local_dt(s.created_at))
    return ordered[-1].status == "creating"


def _generate_snapshot_name(volume_id: str, now: datetime) -> str:
    return f"{AUTO_SNAPSHOT_NAME_PREFIX}-{volume_id[:8]}-" f"{now.strftime('%Y%m%d-%H%M%S')}"


def _to_local_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)
