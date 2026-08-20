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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from skyline_apiserver import schemas
from skyline_apiserver.api import deps
from skyline_apiserver.client import k8s
from skyline_apiserver.db import api as db_api
from skyline_apiserver.types import constants
from skyline_apiserver.utils.roles import (
    assert_system_admin,
    is_system_admin,
)

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Cluster not found.",
    )


async def _assert_cluster_exist(cluster_id: str) -> Any:
    cluster = await db_api.get_managed_cluster(cluster_id)
    if cluster is None:
        raise _not_found()
    return cluster


def _cluster_to_response(cluster: Any) -> schemas.ClusterResponse:
    return schemas.ClusterResponse(
        id=cluster["id"],
        name=cluster["name"],
        address=cluster["address"],
        status=cluster["status"],
        user_id=cluster["user_id"],
        user_name=cluster["user_name"],
        project_id=cluster["project_id"],
        project_name=cluster["project_name"],
        created_at=cluster["created_at"],
        updated_at=cluster["updated_at"],
    )


@router.post(
    "/clusters",
    description=(
        "Onboard a Kubernetes cluster. The provided config yaml is validated "
        "against the address before the cluster is created."
    ),
    responses={
        200: {"model": schemas.ClusterResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.ClusterResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def create_cluster(
    payload: schemas.ClusterCreate,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.ClusterResponse:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to onboard clusters.",
    )
    try:
        k8s.validate_config(payload.address, payload.config_yaml)
        await k8s.check_connectivity(payload.address, payload.config_yaml)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    cluster_id = str(uuid.uuid4())
    try:
        await db_api.create_managed_cluster(
            cluster_id=cluster_id,
            name=payload.name,
            address=payload.address,
            config_yaml=payload.config_yaml,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    cluster = await _assert_cluster_exist(cluster_id)
    return _cluster_to_response(cluster)


@router.get(
    "/clusters",
    description="List managed clusters.",
    responses={
        200: {"model": schemas.ClusterListResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.ClusterListResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def list_clusters(
    search: str = Query(
        None,
        description="Search the cluster by ID, name or address.",
    ),
    limit: int = Query(
        None,
        description="Number of items to return.",
        gt=0,
    ),
    offset: int = Query(
        None,
        description="The number of items to skip before collecting the result set.",
        ge=0,
    ),
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.ClusterListResponse:
    try:
        clusters, count = await db_api.list_managed_clusters(
            search=search,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    result = [_cluster_to_response(cluster) for cluster in clusters]
    return schemas.ClusterListResponse(
        count=count,
        clusters=result,
    )


@router.get(
    "/clusters/{cluster_id}",
    description="Get a managed cluster detail.",
    responses={
        200: {"model": schemas.ClusterResponse},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.ClusterResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def get_cluster(
    cluster_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.ClusterResponse:
    cluster = await _assert_cluster_exist(cluster_id)
    return _cluster_to_response(cluster)


@router.put(
    "/clusters/{cluster_id}/status",
    description=(
        "Change the cluster status. Supported transitions: "
        "unassigned -> assigning, assigning -> assigned, assigning -> unassigned. "
        "When a cluster is assigned (unassigned -> assigning or assigning -> assigned), "
        "the applicant user and project are recorded."
    ),
    responses={
        200: {"model": schemas.ClusterResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.ClusterResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def update_cluster_status(
    cluster_id: str,
    payload: schemas.ClusterStatusUpdate,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.ClusterResponse:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to update cluster status.",
    )
    cluster = await _assert_cluster_exist(cluster_id)
    current = cluster["status"]
    target = payload.status
    allowed = constants.CLUSTER_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cluster status can not be changed from %s to %s."
            % (current, target),
        )
    is_application = (
        current == constants.CLUSTER_STATUS_UNASSIGNED
        and target == constants.CLUSTER_STATUS_ASSIGNING
    )
    if is_application:
        if is_system_admin(profile):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only ordinary users can apply for a cluster.",
            )
    else:
        assert_system_admin(
            profile=profile,
            exception="Not allowed to update cluster status.",
        )
    try:
        if target == constants.CLUSTER_STATUS_UNASSIGNED:
            await db_api.update_managed_cluster_status(
                cluster_id=cluster_id,
                status=target,
            )
        else:
            await db_api.update_managed_cluster_status(
                cluster_id=cluster_id,
                status=target,
                user_id=cluster["user_id"] or profile.user.id,
                user_name=cluster["user_name"] or profile.user.name,
                project_id=cluster["project_id"] or profile.project.id,
                project_name=cluster["project_name"] or profile.project.name,
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return _cluster_to_response(await _assert_cluster_exist(cluster_id))


@router.post(
    "/clusters/{cluster_id}/token",
    description="Get a token to access the cluster dashboard.",
    responses={
        200: {"model": schemas.ClusterTokenResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.ClusterTokenResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def get_cluster_token(
    cluster_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.ClusterTokenResponse:
    cluster = await _assert_cluster_exist(cluster_id)
    if not is_system_admin(profile) and cluster["user_id"] != profile.user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this cluster.",
        )
    try:
        token = k8s.get_dashboard_token(cluster["config_yaml"])
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    return schemas.ClusterTokenResponse(token=token)


@router.delete(
    "/clusters/{cluster_id}",
    description="Delete a managed cluster. Only unassigned clusters can be deleted.",
    responses={
        200: {"model": schemas.Message},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.Message,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def delete_cluster(
    cluster_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.Message:
    assert_system_admin(
        profile=profile,
        exception="Not allowed to delete clusters.",
    )
    cluster = await _assert_cluster_exist(cluster_id)
    if cluster["status"] != constants.CLUSTER_STATUS_UNASSIGNED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the unassigned cluster can be deleted.",
        )
    try:
        await db_api.delete_managed_cluster(cluster_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return schemas.Message(message="Cluster deleted.")
