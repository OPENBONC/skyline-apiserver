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
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from skyline_apiserver import schemas
from skyline_apiserver.api import deps
from skyline_apiserver.client import utils
from skyline_apiserver.client.openstack import quota as quota_client
from skyline_apiserver.db import api as db_api
from skyline_apiserver.types import constants
from skyline_apiserver.utils.roles import assert_system_admin, is_system_admin

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Quota order not found.",
    )


async def _assert_order_exist(order_id: str) -> Any:
    order = await db_api.get_quota_order(order_id)
    if order is None:
        raise _not_found()
    return order


def _order_to_response(order: Any) -> schemas.QuotaOrderResponse:
    return schemas.QuotaOrderResponse(
        id=order["id"],
        title=order["title"],
        quota=order["quota"],
        status=order["status"],
        user_id=order["user_id"],
        user_name=order["user_name"],
        project_id=order["project_id"],
        project_name=order["project_name"],
        created_at=order["created_at"],
        ended_at=order["ended_at"],
    )


@router.post(
    "/quota-orders",
    description="Create a quota application order",
    responses={
        200: {"model": schemas.QuotaOrderResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.QuotaOrderResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def create_quota_order(
    payload: schemas.QuotaOrderCreate,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.QuotaOrderResponse:
    order_id = str(uuid.uuid4())
    try:
        await db_api.create_quota_order(
            order_id=order_id,
            title=payload.title,
            quota=payload.quota,
            user_id=profile.user.id,
            user_name=profile.user.name,
            project_id=profile.project.id,
            project_name=profile.project.name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return await _get_order_response(order_id)


async def _get_order_response(order_id: str) -> schemas.QuotaOrderResponse:
    order = await _assert_order_exist(order_id)
    return _order_to_response(order)


@router.get(
    "/quota-orders",
    description=(
        "List quota orders. Ordinary users only see the orders they created, "
        "while administrators see all the orders."
    ),
    responses={
        200: {"model": schemas.QuotaOrderListResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.QuotaOrderListResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def list_quota_orders(
    search: str = Query(
        None,
        description="Search the quota order by the exact order ID.",
    ),
    status_list: List[str] = Query(
        [],
        description=(
            "Filter by order status. "
            "Options: pending, withdrawn, approved, rejected."
        ),
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
) -> schemas.QuotaOrderListResponse:
    statuses = _validate_statuses(status_list)
    try:
        user_id = None if is_system_admin(profile) else profile.user.id
        orders, count = await db_api.list_quota_orders(
            user_id=user_id,
            statuses=statuses,
            search=search,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    result = [_order_to_response(order) for order in orders]
    return schemas.QuotaOrderListResponse(
        count=count,
        quota_orders=result,
    )


def _validate_statuses(status_list: List[str]) -> Optional[List[str]]:
    if not status_list:
        return None
    invalid = set(status_list) - constants.QUOTA_ORDER_STATUSES
    if invalid:
        raise ValueError("Invalid quota order status: %s" % ", ".join(sorted(invalid)))
    return list(status_list)


@router.get(
    "/quota-orders/{order_id}",
    description="Get a quota order detail",
    responses={
        200: {"model": schemas.QuotaOrderResponse},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.QuotaOrderResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def get_quota_order(
    order_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.QuotaOrderResponse:
    order = await _assert_order_exist(order_id)
    if not is_system_admin(profile) and order["user_id"] != profile.user.id:
        raise _not_found()
    return _order_to_response(order)


@router.post(
    "/quota-orders/{order_id}/withdraw",
    description=(
        "Withdraw a pending quota order. Only the creator can withdraw "
        "his/her own order."
    ),
    responses={
        200: {"model": schemas.QuotaOrderResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.QuotaOrderResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def withdraw_quota_order(
    order_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.QuotaOrderResponse:
    order = await _assert_order_exist(order_id)
    if order["user_id"] != profile.user.id:
        raise _not_found()
    if order["status"] != constants.QUOTA_ORDER_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the pending quota order can be withdrawn.",
        )
    try:
        await db_api.update_quota_order_status(
            order_id=order_id,
            status=constants.QUOTA_ORDER_STATUS_WITHDRAWN,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return await _get_order_response(order_id)


@router.post(
    "/quota-orders/{order_id}/approve",
    description=(
        "Approve a pending quota order and expand the project quota "
        "by calling the OpenStack APIs."
    ),
    responses={
        200: {"model": schemas.QuotaOrderResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.QuotaOrderResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def approve_quota_order(
    order_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
    x_openstack_request_id: str = Header(
        "",
        alias=constants.INBOUND_HEADER,
        regex=constants.INBOUND_HEADER_REGEX,
    ),
) -> schemas.QuotaOrderResponse:
    assert_system_admin(
        profile=profile, exception="Not allowed to approve quota orders."
    )
    order = await _assert_order_exist(order_id)
    if order["status"] != constants.QUOTA_ORDER_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the pending quota order can be approved.",
        )

    region = profile.region
    session = await utils.generate_session(profile)
    try:
        await quota_client.update_quotas(
            session=session,
            region=region,
            project_id=order["project_id"],
            quota=order["quota"],
            global_request_id=x_openstack_request_id,
        )
        await db_api.update_quota_order_status(
            order_id=order_id,
            status=constants.QUOTA_ORDER_STATUS_APPROVED,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return await _get_order_response(order_id)


@router.post(
    "/quota-orders/{order_id}/reject",
    description="Reject a pending quota order",
    responses={
        200: {"model": schemas.QuotaOrderResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
        403: {"model": schemas.ForbiddenMessage},
        404: {"model": schemas.NotFoundMessage},
        500: {"model": schemas.InternalServerErrorMessage},
    },
    response_model=schemas.QuotaOrderResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def reject_quota_order(
    order_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.QuotaOrderResponse:
    assert_system_admin(
        profile=profile, exception="Not allowed to reject quota orders."
    )
    order = await _assert_order_exist(order_id)
    if order["status"] != constants.QUOTA_ORDER_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the pending quota order can be rejected.",
        )
    try:
        await db_api.update_quota_order_status(
            order_id=order_id,
            status=constants.QUOTA_ORDER_STATUS_REJECTED,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return await _get_order_response(order_id)
