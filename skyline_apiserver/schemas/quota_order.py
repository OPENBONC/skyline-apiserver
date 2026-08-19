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


class QuotaOrderCreate(BaseModel):
    title: str = Field(..., description="Quota order title, no more than 60 characters")
    quota: Dict[str, Any] = Field(
        ..., description="Quota to apply for, e.g. {'instances': 20}"
    )

    @validator("title")
    def check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title must not be empty.")
        if len(v) > 60:
            raise ValueError("Title must be no more than 60 characters.")
        return v

    @validator("quota")
    def check_quota(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("Please apply for at least one quota item.")
        for key, value in v.items():
            if value is None or int(value) <= 0:
                raise ValueError("Quota value must be a positive integer.")
        return {key: int(value) for key, value in v.items()}


class QuotaOrderResponse(BaseModel):
    id: str = Field(..., description="Quota order ID / the order number")
    title: str = Field(..., description="Quota order title")
    quota: Dict[str, Any] = Field(..., description="Quota applied for")
    status: str = Field(..., description="Quota order status")
    user_id: str = Field(..., description="The ID of the user who created the order")
    user_name: str = Field(
        ..., description="The name of the user who created the order"
    )
    project_id: str = Field(..., description="The project ID applying for quota")
    project_name: Optional[str] = Field(
        None, description="The project name applying for quota"
    )
    created_at: str = Field(..., description="Order created at time")
    ended_at: Optional[str] = Field(None, description="Order ended at time")


class QuotaOrderListResponse(BaseModel):
    count: int = Field(0, description="The number of quota orders")
    quota_orders: List[QuotaOrderResponse] = Field(..., description="Quota orders list")
