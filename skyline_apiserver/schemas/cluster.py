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

from typing import List, Optional

from pydantic import BaseModel, Field, validator

from skyline_apiserver.types import constants


class ClusterCreate(BaseModel):
    name: str = Field(..., description="Cluster name")
    address: str = Field(
        ..., description="Cluster API server address, e.g. https://1.2.3.4:6443"
    )
    config_yaml: str = Field(..., description="Kubernetes config yaml content")
    dashboard_url: Optional[str] = Field(
        None, description="Cluster dashboard URL, e.g. https://dashboard.example.com"
    )

    @validator("name")
    def check_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be empty.")
        if len(v) > 255:
            raise ValueError("Name must be no more than 255 characters.")
        return v

    @validator("address")
    def check_address(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v:
            raise ValueError("Address must not be empty.")
        if len(v) > 255:
            raise ValueError("Address must be no more than 255 characters.")
        return v

    @validator("config_yaml")
    def check_config_yaml(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Config yaml must not be empty.")
        return v

    @validator("dashboard_url")
    def check_dashboard_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().rstrip("/")
        if not v:
            return None
        if len(v) > 255:
            raise ValueError("Dashboard URL must be no more than 255 characters.")
        return v


class ClusterStatusUpdate(BaseModel):
    status: str = Field(..., description="Target cluster status")

    @validator("status")
    def check_status(cls, v: str) -> str:
        if v not in constants.CLUSTER_STATUSES:
            raise ValueError(
                "Invalid cluster status: %s"
                % ", ".join(sorted(constants.CLUSTER_STATUSES))
            )
        return v


class ClusterResponse(BaseModel):
    id: str = Field(..., description="Cluster ID")
    name: str = Field(..., description="Cluster name")
    address: str = Field(..., description="Cluster API server address")
    dashboard_url: Optional[str] = Field(None, description="Cluster dashboard URL")
    status: str = Field(..., description="Cluster status")
    user_id: Optional[str] = Field(
        None, description="The ID of the user who applied the cluster"
    )
    user_name: Optional[str] = Field(
        None, description="The name of the user who applied the cluster"
    )
    project_id: Optional[str] = Field(
        None, description="The project ID of the applicant"
    )
    project_name: Optional[str] = Field(
        None, description="The project name of the applicant"
    )
    created_at: int = Field(..., description="Cluster created at timestamp (ms)")
    updated_at: int = Field(..., description="Cluster updated at timestamp (ms)")


class ClusterListResponse(BaseModel):
    count: int = Field(0, description="The number of managed clusters")
    clusters: List[ClusterResponse] = Field(..., description="Managed clusters list")


class ClusterTokenResponse(BaseModel):
    token: str = Field(..., description="Dashboard access token")
