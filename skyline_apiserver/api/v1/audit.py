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

import json
import time
import uuid
from typing import Any, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from skyline_apiserver import schemas
from skyline_apiserver.api import deps
from skyline_apiserver.db import api as db_api
from skyline_apiserver.types import constants

router = APIRouter()


def _is_login_logout_log(request_path: str) -> bool:
    path = request_path.lower()
    return "login" in path or "logout" in path


def _is_login_logout_action(action: Optional[str]) -> bool:
    if not action:
        return False
    action = action.lower()
    return "login" in action or "logout" in action


def _parse_identity_from_request_body(
    request_body: Optional[str],
) -> Tuple[str, str, str, str]:
    empty: Tuple[str, str, str, str] = ("", "", "", "")
    if not request_body:
        return empty
    try:
        data = json.loads(request_body)
    except (ValueError, TypeError):
        return empty
    if not isinstance(data, dict):
        return empty
    domain_name = str(data.get("domain") or "")
    user_name = str(data.get("username") or "")
    return "", domain_name, "", user_name


def _get_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def _deserialize_targets(raw: Optional[str]) -> List[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _row_to_view(row: Any) -> schemas.AuditLogView:
    data = dict(row)
    data["targets"] = _deserialize_targets(data.get("targets"))
    return schemas.AuditLogView(**data)


def _row_to_detail_view(row: Any, detail: Any) -> schemas.AuditLogDetailView:
    data = dict(row)
    data["targets"] = _deserialize_targets(data.get("targets"))
    data.update({k: v for k, v in dict(detail).items() if k != "log_id"})
    return schemas.AuditLogDetailView(**data)


@router.post(
    "/audit/logs",
    description="Create an audit log.",
    responses={
        200: {"model": schemas.AuditLogView},
        401: {"model": schemas.UnauthorizedMessage},
    },
    response_model=schemas.AuditLogView,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def create_audit_log(
    request: Request,
    payload: schemas.AuditLogCreate,
    profile: Optional[schemas.Profile] = Depends(deps.get_profile_update_jwt_optional),
) -> schemas.AuditLogView:
    now_ms = int(time.time() * 1000)
    log_id = uuid.uuid4().hex
    targets = payload.targets
    target_names = ",".join(t.name for t in targets if t.name)
    source_ip = _get_client_ip(request)

    if profile is not None:
        domain_id = profile.user.domain.id
        domain_name = profile.user.domain.name
        user_id = profile.user.id
        user_name = profile.user.name
    else:
        if not _is_login_logout_log(payload.request_path):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=constants.ERR_MSG_TOKEN_NOTFOUND,
            )
        domain_id, domain_name, user_id, user_name = _parse_identity_from_request_body(
            payload.request_body
        )

    main_values = {
        "id": log_id,
        "domain_id": domain_id,
        "domain_name": domain_name,
        "project_id": payload.project_id,
        "project_name": payload.project_name,
        "user_id": user_id,
        "user_name": user_name,
        "module": payload.module,
        "action": payload.action,
        "targets": json.dumps([t.dict() for t in targets], ensure_ascii=False),
        "target_names": target_names,
        "source_ip": source_ip,
        "request_result": payload.request_result,
    }
    detail_values = {
        "log_id": log_id,
        "trace_id": payload.trace_id,
        "request_method": payload.request_method,
        "request_path": payload.request_path,
        "request_body": payload.request_body,
        "http_code": payload.http_code,
        "error_code": payload.error_code,
        "error_message": payload.error_message,
    }
    await db_api.create_audit_log(main_values, detail_values, now_ms)

    return schemas.AuditLogView(
        id=log_id,
        domain_id=domain_id,
        domain_name=domain_name,
        project_id=payload.project_id,
        project_name=payload.project_name,
        user_id=user_id,
        user_name=user_name,
        module=payload.module,
        action=payload.action,
        targets=targets,
        source_ip=source_ip,
        created_at=now_ms,
        updated_at=now_ms,
        request_result=payload.request_result,
    )


@router.put(
    "/audit/logs/{log_id}",
    description="Update an audit log result information.",
    responses={
        204: {"model": None},
        401: {"model": schemas.UnauthorizedMessage},
        404: {"model": schemas.NotFoundMessage},
    },
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="No Content",
)
async def update_audit_log(
    log_id: str,
    payload: schemas.AuditLogUpdate,
    profile: Optional[schemas.Profile] = Depends(deps.get_profile_update_jwt_optional),
) -> Response:
    if all(
        field is None
        for field in (
            payload.request_result,
            payload.http_code,
            payload.error_code,
            payload.error_message,
        )
    ):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if profile is not None:
        domain_id = profile.user.domain.id
        domain_name = profile.user.domain.name
        user_id = profile.user.id
        user_name = profile.user.name
    else:
        if not _is_login_logout_action(payload.action):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=constants.ERR_MSG_TOKEN_NOTFOUND,
            )
        domain_id = ""
        domain_name = None
        user_id = None
        user_name = None

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=domain_id,
        now_ms=int(time.time() * 1000),
        request_result=payload.request_result,
        http_code=payload.http_code,
        error_code=payload.error_code,
        error_message=payload.error_message,
        domain_name=domain_name,
        user_id=user_id,
        user_name=user_name,
    )
    if result == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/audit/logs",
    description="List audit logs.",
    responses={
        200: {"model": schemas.AuditLogListResponse},
        400: {"model": schemas.BadRequestMessage},
        401: {"model": schemas.UnauthorizedMessage},
    },
    response_model=schemas.AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def list_audit_logs(
    project_id: Optional[str] = Query(None, description="项目 ID，精确匹配"),
    start_time: Optional[int] = Query(None, description="请求时间范围开始值，毫秒时间戳"),
    end_time: Optional[int] = Query(None, description="请求时间范围结束值，毫秒时间戳"),
    operator_name: Optional[str] = Query(None, description="操作人名称，忽略大小写的模糊匹配"),
    module: Optional[str] = Query(None, description="所属模块，精确匹配"),
    action: Optional[str] = Query(None, description="动作类型，精确匹配"),
    request_result: Optional[str] = Query(None, description="请求结果，精确匹配"),
    target: Optional[str] = Query(None, description="操作对象 ID 或名称，忽略大小写的模糊匹配"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(10, ge=1, le=100, description="每页大小"),
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.AuditLogListResponse:
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid time range.",
        )

    total, rows = await db_api.list_audit_logs(
        domain_name=profile.user.domain.name,
        page=page,
        size=size,
        project_id=project_id or None,
        start_time=start_time,
        end_time=end_time,
        operator_name=operator_name or None,
        module=module or None,
        action=action or None,
        request_result=request_result or None,
        target=target or None,
    )
    return schemas.AuditLogListResponse(
        total=total,
        page=page,
        size=size,
        items=[_row_to_view(row) for row in rows],
    )


@router.get(
    "/audit/logs/{log_id}",
    description="Get an audit log detail.",
    responses={
        200: {"model": schemas.AuditLogDetailView},
        401: {"model": schemas.UnauthorizedMessage},
        404: {"model": schemas.NotFoundMessage},
    },
    response_model=schemas.AuditLogDetailView,
    status_code=status.HTTP_200_OK,
    response_description="OK",
)
async def get_audit_log_detail(
    log_id: str,
    profile: schemas.Profile = Depends(deps.get_profile_update_jwt),
) -> schemas.AuditLogDetailView:
    row = await db_api.get_audit_log(log_id, profile.user.domain.name)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log not found.",
        )
    detail = await db_api.get_audit_log_detail(log_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log not found.",
        )
    return _row_to_detail_view(row, detail)
