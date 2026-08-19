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

from typing import Any, Dict

from fastapi import HTTPException, status
from keystoneauth1.exceptions.http import Unauthorized
from keystoneauth1.session import Session
from starlette.concurrency import run_in_threadpool

from skyline_apiserver.client import utils

# Quota keys which are accepted by each OpenStack service.
# NOTE: nova is pinned to API 2.79, whose quota update only accepts these keys.
NOVA_QUOTA_KEYS = {
    "instances",
    "cores",
    "ram",
    "metadata_items",
    "key_pairs",
    "server_groups",
    "server_group_members",
}
CINDER_QUOTA_KEYS = {
    "volumes",
    "snapshots",
    "gigabytes",
    "per_volume_gigabytes",
    "backups",
    "backup_gigabytes",
}
NEUTRON_QUOTA_KEYS = {
    "network",
    "subnet",
    "port",
    "router",
    "floatingip",
    "security_group",
    "security_group_rule",
    "subnetpool",
    "vip",
}


def _split_quotas(quota: Dict[str, Any]) -> Any:
    nova = {k: v for k, v in quota.items() if k in NOVA_QUOTA_KEYS}
    cinder = {k: v for k, v in quota.items() if k in CINDER_QUOTA_KEYS}
    neutron = {k: v for k, v in quota.items() if k in NEUTRON_QUOTA_KEYS}
    unsupported = set(quota) - NOVA_QUOTA_KEYS - CINDER_QUOTA_KEYS - NEUTRON_QUOTA_KEYS
    return nova, cinder, neutron, unsupported


async def update_quotas(
    session: Session,
    region: str,
    project_id: str,
    quota: Dict[str, Any],
    global_request_id: str = "",
) -> Any:
    nova, cinder, neutron, unsupported = _split_quotas(quota)
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported quota keys: %s" % ", ".join(sorted(unsupported)),
        )
    try:
        if nova:
            nc = await utils.nova_client(
                region=region,
                session=session,
                global_request_id=global_request_id,
            )
            await run_in_threadpool(nc.quotas.update, project_id, **nova)
        if cinder:
            cc = await utils.cinder_client(
                region=region,
                session=session,
                global_request_id=global_request_id,
            )
            await run_in_threadpool(cc.quotas.update, project_id, **cinder)
        if neutron:
            nc = await utils.neutron_client(
                region=region,
                session=session,
                global_request_id=global_request_id,
            )
            await run_in_threadpool(
                nc.update_quota,
                project_id,
                body={"quota": neutron},
            )
    except Unauthorized as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return None
