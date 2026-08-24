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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from skyline_apiserver.types import constants


class QuotaOrderCreate(BaseModel):
    type: str = Field(
        constants.RESOURCE_ORDER_TYPE_QUOTA,
        description="Order type: quota or cluster",
    )
    title: str = Field(..., description="Order title, no more than 60 characters")
    quota: Optional[Dict[str, Any]] = Field(
        None,
        description="Quota to apply for, e.g. {'instances': 20}, required for quota orders",
    )
    cluster_id: Optional[str] = Field(
        None, description="Cluster ID to apply for, required for cluster orders"
    )

    @validator("type")
    def check_type(cls, v: str) -> str:
        if v not in constants.RESOURCE_ORDER_TYPES:
            raise ValueError(
                "Invalid order type: %s"
                % ", ".join(sorted(constants.RESOURCE_ORDER_TYPES))
            )
        return v

    @validator("title")
    def check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title must not be empty.")
        if len(v) > 60:
            raise ValueError("Title must be no more than 60 characters.")
        return v

    @validator("quota")
    def check_quota(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        if not v:
            raise ValueError("Please apply for at least one quota item.")
        for key, value in v.items():
            if value is None or int(value) <= 0:
                raise ValueError("Quota value must be a positive integer.")
        return {key: int(value) for key, value in v.items()}

    @validator("cluster_id")
    def check_cluster_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None


class QuotaOrderResponse(BaseModel):
    id: str = Field(..., description="Order ID / the order number")
    type: str = Field(
        constants.RESOURCE_ORDER_TYPE_QUOTA, description="Order type: quota or cluster"
    )
    title: str = Field(..., description="Order title")
    quota: Optional[Dict[str, Any]] = Field(None, description="Quota applied for")
    cluster_id: Optional[str] = Field(None, description="Cluster ID applied for")
    status: str = Field(..., description="Order status")
    user_id: str = Field(..., description="The ID of the user who created the order")
    user_name: str = Field(
        ..., description="The name of the user who created the order"
    )
    project_id: str = Field(..., description="The project ID applying for quota")
    project_name: Optional[str] = Field(
        None, description="The project name applying for quota"
    )
    created_at: int = Field(..., description="Order created at timestamp (ms)")
    ended_at: Optional[int] = Field(None, description="Order ended at timestamp (ms)")


class QuotaOrderListResponse(BaseModel):
    count: int = Field(0, description="The number of orders")
    quota_orders: List[QuotaOrderResponse] = Field(..., description="Orders list")
