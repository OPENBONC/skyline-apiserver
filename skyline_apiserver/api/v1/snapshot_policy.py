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

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response

from skyline_apiserver import schemas
from skyline_apiserver.api import deps
from skyline_apiserver.client import utils
from skyline_apiserver.client.openstack import cinder
from skyline_apiserver.config import CONF
from skyline_apiserver.db import api as db_api
from skyline_apiserver.log import LOG
from skyline_apiserver.types import constants
from skyline_apiserver.utils.roles import assert_system_admin, assert_system_admin_or_reader

router = APIRouter()

STEP = constants.ID_UUID_RANGE_STEP


def _create_trust(trustor_user_id: str, trustee_user_id: str, trustor_project_id: str, user_session=None) -> str:
    """
    创建 OpenStack Trust
    :param trustor_user_id: 委托人用户ID (策略创建用户)
    :param trustee_user_id: 受托人用户ID (系统用户)
    :param trustor_project_id: 委托人项目ID (要委托的项目)
    :param user_session: 委托人的 session (用于创建 trust)
    :return: trust_id
    """
    session = user_session or utils.get_system_session()

    # 获取 trustor 用户在项目上的角色
    ks = __import__("keystoneclient").client.Client(session=session)
    role_list = ks.roles.list(user=trustor_user_id, project=trustor_project_id)
    roles_data = [{"name": r.name} for r in role_list]
    LOG.info(f"Trust roles for user {trustor_user_id} on project {trustor_project_id}: {[r['name'] for r in roles_data]}")

    # 使用 REST API 创建 trust，避免 keystoneclient 内部 roles 参数冲突
    body = {
        "trust": {
            "trustor_user_id": trustor_user_id,
            "trustee_user_id": trustee_user_id,
            "project_id": trustor_project_id,
            "impersonation": True,
            "allow_redelegation": False,
            "roles": roles_data,
        }
    }

    url = f"{CONF.openstack.keystone_url}/OS-TRUST/trusts"
    resp = session.post(url, json=body)
    trust_data = resp.json()
    trust_id = trust_data["trust"]["id"]
    LOG.info(f"Created Trust: {trust_id} (trustor={trustor_user_id}, trustee={trustee_user_id}, project={trustor_project_id})")
    return trust_id


def _not_found(exception: str = "Snapshot policy not found.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=exception,
    )


async def _assert_policy_exist(policy_id: str) -> Any:
    policy = await db_api.get_snapshot_policy(policy_id)
    if policy is None:
        raise _not_found()
    return policy


def _volume_to_dict(volume: Any) -> Dict[str, Any]:
    return {
        "id": volume.id,
        "name": volume.name,
        "size": getattr(volume, "size", None),
        "status": getattr(volume, "status", None),
        "bootable": getattr(volume, "bootable", None),
        "attached": bool(getattr(volume, "attachments", None) or []),
        "project_id": getattr(volume, "os-vol-tenant-attr:tenant_id", None),
    }


async def _list_user_volumes(
    profile: schemas.Profile,
    user_session: Any,
    global_request_id: str,
) -> List[Any]:
    volumes, _ = await cinder.list_volumes(
        profile=profile,
        session=user_session,
        global_request_id=global_request_id,
        search_opts={"with_count": True},
    )
    return list(volumes)


@router.get(
    "/snapshot-policies",
    description="List scheduled snapshot policies",
    responses={
        200: {"model": schemas.SnapshotPolicyListResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.SnapshotPolicyListResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def list_snapshot_policies(
    search: str = Query(
        None,
        description="Search the snapshot policy by the exact policy ID.",
    ),
    limit: int = Query(
        None,
        description=(
            "Requests a page size of items. Returns a number of items up to a limit value."
        ),
        gt=0,
    ),
    offset: int = Query(
        None,
        description="The number of items to skip before starting to collect the result set.",
        ge=0,
    ),
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
    x_openstack_request_id: str = Header(
        "",
        alias=constants.INBOUND_HEADER,
        regex=constants.INBOUND_HEADER_REGEX,
    ),
) -> schemas.SnapshotPolicyListResponse:
    assert_system_admin_or_reader(
        profile=profile,
        exception="Not allowed to get scheduled snapshot policies.",
    )
    try:
        policies, count = await db_api.list_snapshot_policies(
            search=search,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    result = [
        schemas.SnapshotPolicyResponse(
            id=policy["id"],
            name=policy["name"],
            repeat_days=policy["repeat_days"],
            create_times=policy["create_times"],
            trust_id=policy["trust_id"],
            volume_count=policy["volume_count"],
            created_at=policy["created_at"],
            updated_at=policy["updated_at"],
            volumes=[],
        )
        for policy in policies
    ]
    await _fill_policy_volumes(profile, result, x_openstack_request_id)
    return schemas.SnapshotPolicyListResponse(
        count=count,
        snapshot_policies=result,
    )


@router.post(
    "/snapshot-policies",
    description="Create a scheduled snapshot policy",
    responses={
        200: {"model": schemas.SnapshotPolicyResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.SnapshotPolicyResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def create_snapshot_policy(
    payload: schemas.SnapshotPolicyCreate,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.SnapshotPolicyResponse:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to create scheduled snapshot policies.",
    )
    policy_id = str(uuid.uuid4())

    # 创建 Trust：委托人=策略创建用户，受托人=系统用户
    trust_id = None
    try:
        user_session = await utils.generate_session(profile)
        trust_id = _create_trust(
            trustor_user_id=profile.user.id,
            trustee_user_id=CONF.openstack.system_user_id,
            trustor_project_id=profile.project.id,
            user_session=user_session,
        )
    except Exception as e:
        LOG.warning(f"Failed to create trust for policy {policy_id}: {e}")

    try:
        await _assert_volumes_available(payload.volume_ids, policy_id)
        await db_api.create_snapshot_policy(
            policy_id=policy_id,
            name=payload.name,
            repeat_days=payload.repeat_days,
            create_times=payload.create_times,
            volume_ids=payload.volume_ids,
            user_id=profile.user.id,
            user_name=profile.user.name,
            project_id=profile.project.id,
            project_name=profile.project.name,
            trust_id=trust_id,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return await _get_policy_response(profile, policy_id)


@router.get(
    "/snapshot-policies/available-volumes",
    description=(
        "List volumes which are not bound to any other scheduled snapshot policy, "
        "so that they can be added to the given policy."
    ),
    responses={
        200: {"model": schemas.AvailableVolumesResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.AvailableVolumesResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def list_available_volumes(
    policy_id: str = Query(
        None,
        description=(
            "The ID of the snapshot policy being edited. Volumes already bound "
            "to this policy will keep being selectable."
        ),
    ),
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
    x_openstack_request_id: str = Header(
        "",
        alias=constants.INBOUND_HEADER,
        regex=constants.INBOUND_HEADER_REGEX,
    ),
) -> schemas.AvailableVolumesResponse:
    assert_system_admin_or_reader(
        profile=profile,
        exception="Not allowed to get available volumes.",
    )
    try:
        # project_session = utils.get_system_session_by_project(profile.project.id)
        user_session = await utils.generate_session(profile)
        volumes = await _list_user_volumes(
            profile, user_session, x_openstack_request_id
        )
        bound_rows = await db_api.list_policy_volumes()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    bound_mapping: Dict[str, str] = {
        row["volume_id"]: row["policy_id"] for row in bound_rows
    }
    result = []
    for volume in volumes:
        existed_policy_id = bound_mapping.get(volume.id)
        if existed_policy_id is not None and existed_policy_id != policy_id:
            continue
        item = _volume_to_dict(volume)
        item["policy_id"] = existed_policy_id
        result.append(item)

    return schemas.AvailableVolumesResponse(
        count=len(result),
        volumes=[schemas.AvailableVolumeResponse(**item) for item in result],
    )


@router.get(
    "/snapshot-policies/{policy_id}",
    description="Get a scheduled snapshot policy",
    responses={
        200: {"model": schemas.SnapshotPolicyResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.SnapshotPolicyResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def get_snapshot_policy(
    policy_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
    x_openstack_request_id: str = Header(
        "",
        alias=constants.INBOUND_HEADER,
        regex=constants.INBOUND_HEADER_REGEX,
    ),
) -> schemas.SnapshotPolicyResponse:
    assert_system_admin_or_reader(
        profile=profile,
        exception="Not allowed to get scheduled snapshot policies.",
    )
    _ = await _assert_policy_exist(policy_id)
    return await _get_policy_response(profile, policy_id, x_openstack_request_id)


async def _get_policy_response(
    profile: schemas.Profile,
    policy_id: str,
    global_request_id: str = "",
) -> schemas.SnapshotPolicyResponse:
    policy = await _assert_policy_exist(policy_id)
    response = schemas.SnapshotPolicyResponse(
        id=policy["id"],
        name=policy["name"],
        repeat_days=policy["repeat_days"],
        create_times=policy["create_times"],
        trust_id=policy["trust_id"],
        volume_count=0,
        created_at=policy["created_at"],
        updated_at=policy["updated_at"],
        volumes=[],
    )
    await _fill_policy_volumes(profile, [response], global_request_id)
    return response


async def _resolve_volumes(
    profile: schemas.Profile,
    volume_ids: List[str],
    global_request_id: str,
) -> List[Any]:
    if not volume_ids:
        return []
    system_session = utils.get_system_session()
    result: List[Any] = []
    for i in range(0, len(volume_ids), STEP):
        volumes, _ = await cinder.list_volumes(
            profile=profile,
            session=system_session,
            global_request_id=global_request_id,
            search_opts={
                "id": volume_ids[i : i + STEP],
                "all_tenants": True,
                "with_count": True,
            },
        )
        result.extend(volume.to_dict() for volume in volumes)
    return result


async def _fill_policy_volumes(
    profile: schemas.Profile,
    policies: List[schemas.SnapshotPolicyResponse],
    global_request_id: str,
) -> None:
    policy_ids = [policy.id for policy in policies]
    if not policy_ids:
        return
    volume_rows = await db_api.list_policy_volumes()
    rows_by_policy: Dict[str, List[Dict[str, Any]]] = {}
    for row in volume_rows:
        rows_by_policy.setdefault(row["policy_id"], []).append(row)
    all_volume_ids = [
        row["volume_id"] for rows in rows_by_policy.values() for row in rows
    ]
    volume_mapping = {}
    if all_volume_ids:
        volumes = await _resolve_volumes(profile, all_volume_ids, global_request_id)
        volume_mapping = {volume["id"]: volume for volume in volumes}
    for policy in policies:
        rows = rows_by_policy.get(policy.id, [])
        volume_responses = []
        for row in rows:
            volume = volume_mapping.get(row["volume_id"])
            volume_responses.append(
                schemas.SnapshotPolicyVolumeResponse(
                    volume_id=row["volume_id"],
                    volume_name=volume["name"] if volume else None,
                    size=volume["size"] if volume else None,
                    status=volume["status"] if volume else None,
                    bootable=volume["bootable"] if volume else None,
                ),
            )
        policy.volumes = volume_responses
        policy.volume_count = len(volume_responses)


@router.put(
    "/snapshot-policies/{policy_id}",
    description="Update a scheduled snapshot policy",
    responses={
        200: {"model": schemas.SnapshotPolicyResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.SnapshotPolicyResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def update_snapshot_policy(
    policy_id: str,
    payload: schemas.SnapshotPolicyUpdate,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.SnapshotPolicyResponse:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to update scheduled snapshot policies.",
    )
    policy = await _assert_policy_exist(policy_id)

    name = payload.name if payload.name is not None else policy["name"]
    repeat_days = (
        payload.repeat_days
        if payload.repeat_days is not None
        else policy["repeat_days"]
    )
    create_times = (
        payload.create_times
        if payload.create_times is not None
        else policy["create_times"]
    )
    if payload.volume_ids is None:
        volume_rows = await db_api.list_policy_volumes(policy_id=policy_id)
        volume_ids = [row["volume_id"] for row in volume_rows]
    else:
        volume_ids = payload.volume_ids

    try:
        await _assert_volumes_available(volume_ids, policy_id)
        await db_api.update_snapshot_policy(
            policy_id=policy_id,
            name=name,
            repeat_days=repeat_days,
            create_times=create_times,
            volume_ids=volume_ids,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return await _get_policy_response(profile, policy_id)


async def _assert_volumes_available(volume_ids: List[str], policy_id: str) -> None:
    for volume_id in volume_ids:
        existed = await db_api.get_volume_policy(volume_id)
        if existed is not None and existed["policy_id"] != policy_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The volume %s has already been bound to another snapshot policy."
                    % volume_id
                ),
            )


@router.delete(
    "/snapshot-policies/{policy_id}",
    description="Delete a scheduled snapshot policy",
    responses={
        204: {"model": None},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="No Content",
    response_class=Response,
)
async def delete_snapshot_policy(
    policy_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> None:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to delete scheduled snapshot policies.",
    )
    await _assert_policy_exist(policy_id)
    try:
        await db_api.delete_snapshot_policy(policy_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/snapshot-policies/batch-delete",
    description="Batch delete scheduled snapshot policies",
    responses={
        204: {"model": None},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="No Content",
    response_class=Response,
)
async def batch_delete_snapshot_policies(
    payload: schemas.SnapshotPoliciesDelete,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> None:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to delete scheduled snapshot policies.",
    )
    try:
        for policy_id in payload.ids:
            await _assert_policy_exist(policy_id)
        await db_api.delete_snapshot_policies(payload.ids)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
