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

from typing import List, Optional

from pydantic import BaseModel, Field, validator


class Target(BaseModel):
    id: Optional[str] = Field(None, description="操作对象 ID")
    name: Optional[str] = Field(None, description="操作对象名称")
    type: Optional[str] = Field(None, description="资源类型")


class AuditLogCreate(BaseModel):
    project_id: str = Field(..., description="项目 ID")
    project_name: str = Field(..., description="项目名称")
    module: str = Field(..., description="所属模块")
    action: str = Field(..., description="动作类型")
    targets: List[Target] = Field(default_factory=list, description="操作对象数组")
    trace_id: str = Field(..., description="请求 ID")
    request_method: str = Field(..., description="HTTP 请求方法")
    request_path: str = Field(..., description="请求路径，允许包含 query string")
    request_body: Optional[str] = Field(None, description="请求体文本")
    request_result: Optional[str] = Field(None, description="请求结果")
    http_code: Optional[int] = Field(None, description="HTTP 状态码")
    error_code: Optional[str] = Field(None, description="错误码")
    error_message: Optional[str] = Field(None, description="错误信息")

    @validator(
        "project_id",
        "project_name",
        "module",
        "action",
        "trace_id",
        "request_method",
        "request_path",
    )
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field must not be empty.")
        return value


class AuditLogUpdate(BaseModel):
    request_result: Optional[str] = Field(None, description="请求结果")
    http_code: Optional[int] = Field(None, description="HTTP 状态码")
    error_code: Optional[str] = Field(None, description="错误码")
    error_message: Optional[str] = Field(None, description="错误信息")
    action: Optional[str] = Field(None, description="动作类型")


class AuditLogView(BaseModel):
    id: str = Field(..., description="日志 ID")
    domain_id: str = Field(..., description="企业 ID")
    domain_name: Optional[str] = Field(None, description="企业名称")
    project_id: Optional[str] = Field(None, description="项目 ID")
    project_name: Optional[str] = Field(None, description="项目名称")
    user_id: str = Field(..., description="操作人 ID")
    user_name: Optional[str] = Field(None, description="操作人名称")
    module: Optional[str] = Field(None, description="所属模块")
    action: Optional[str] = Field(None, description="动作类型")
    targets: List[Target] = Field(default_factory=list, description="操作对象数组")
    source_ip: Optional[str] = Field(None, description="来源 IP")
    created_at: int = Field(..., description="创建时间，毫秒时间戳")
    updated_at: int = Field(..., description="更新时间，毫秒时间戳")
    request_result: Optional[str] = Field(None, description="请求结果")


class AuditLogDetailView(AuditLogView):
    trace_id: Optional[str] = Field(None, description="请求 ID")
    request_method: Optional[str] = Field(None, description="HTTP 请求方法")
    request_path: Optional[str] = Field(None, description="请求路径")
    request_body: Optional[str] = Field(None, description="请求体文本")
    http_code: Optional[int] = Field(None, description="HTTP 状态码")
    error_code: Optional[str] = Field(None, description="错误码")
    error_message: Optional[str] = Field(None, description="错误信息")


class AuditLogListResponse(BaseModel):
    total: int = Field(..., description="命中总数")
    page: int = Field(..., description="当前页码")
    size: int = Field(..., description="每页大小")
    items: List[AuditLogView] = Field(default_factory=list, description="日志列表")
