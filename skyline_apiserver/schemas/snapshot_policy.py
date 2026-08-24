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


class SnapshotPolicyBase(BaseModel):
    name: Optional[str] = Field(None, description="Scheduled snapshot policy name")
    repeat_days: List[int] = Field(
        ...,
        description="Repeat days, 1 means Monday, 7 means Sunday",
    )
    create_times: List[int] = Field(
        ...,
        description="Create times, the hour of every day to create snapshots, 0-23",
    )

    @validator("repeat_days")
    def check_repeat_days(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("Please select at least one repeat day.")
        for day in v:
            if day < 1 or day > 7:
                raise ValueError("Repeat day must be between 1 and 7.")
        return list(sorted(set(v)))

    @validator("create_times")
    def check_create_times(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("Please select at least one create time.")
        for hour in v:
            if hour < 0 or hour > 23:
                raise ValueError("Create time must be between 0 and 23.")
        return list(sorted(set(v)))


class SnapshotPolicyCreate(SnapshotPolicyBase):
    volume_ids: List[str] = Field(..., description="Volume IDs bound to the policy")

    @validator("volume_ids")
    def check_volume_ids(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("Please select at least one volume.")
        return list(dict.fromkeys(v))


class SnapshotPolicyUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Scheduled snapshot policy name")
    repeat_days: Optional[List[int]] = Field(
        None,
        description="Repeat days, 1 means Monday, 7 means Sunday",
    )
    create_times: Optional[List[int]] = Field(
        None,
        description="Create times, the hour of every day to create snapshots, 0-23",
    )
    volume_ids: Optional[List[str]] = Field(
        None,
        description="Volume IDs bound to the policy",
    )

    @validator("repeat_days")
    def check_repeat_days(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            if not v:
                raise ValueError("Please select at least one repeat day.")
            for day in v:
                if day < 1 or day > 7:
                    raise ValueError("Repeat day must be between 1 and 7.")
            return list(sorted(set(v)))
        return v

    @validator("create_times")
    def check_create_times(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            if not v:
                raise ValueError("Please select at least one create time.")
            for hour in v:
                if hour < 0 or hour > 23:
                    raise ValueError("Create time must be between 0 and 23.")
            return list(sorted(set(v)))
        return v

    @validator("volume_ids")
    def check_volume_ids(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if not v:
                raise ValueError("Please select at least one volume.")
            return list(dict.fromkeys(v))
        return v


class SnapshotPolicyVolumeResponse(BaseModel):
    volume_id: str = Field(..., description="Volume ID")
    volume_name: Optional[str] = Field(None, description="Volume name")
    size: Optional[int] = Field(None, description="Volume size in GB")
    status: Optional[str] = Field(None, description="Volume status")
    bootable: Optional[str] = Field(None, description="Whether the volume is bootable")


class SnapshotPolicyResponse(BaseModel):
    id: str = Field(..., description="Scheduled snapshot policy ID")
    name: Optional[str] = Field(None, description="Scheduled snapshot policy name")
    repeat_days: List[int] = Field(..., description="Repeat days, 1-7")
    create_times: List[int] = Field(..., description="Create times, 0-23")
    volume_count: int = Field(0, description="The number of volumes bound to the policy")
    created_at: int = Field(..., description="Created at timestamp (ms)")
    updated_at: Optional[int] = Field(None, description="Updated at timestamp (ms)")
    volumes: Optional[List[SnapshotPolicyVolumeResponse]] = Field(
        None,
        description="Volumes bound to the policy",
    )


class SnapshotPolicyListResponse(BaseModel):
    count: int = Field(0, description="The number of snapshot policies")
    snapshot_policies: List[SnapshotPolicyResponse] = Field(
        ...,
        description="Snapshot policies list",
    )


class SnapshotPoliciesDelete(BaseModel):
    ids: List[str] = Field(..., description="Snapshot policy IDs to delete")

    @validator("ids")
    def check_ids(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("Please select at least one snapshot policy.")
        return list(dict.fromkeys(v))


class AvailableVolumeResponse(BaseModel):
    id: str = Field(..., description="Volume ID")
    name: Optional[str] = Field(None, description="Volume name")
    size: Optional[int] = Field(None, description="Volume size in GB")
    status: Optional[str] = Field(None, description="Volume status")
    bootable: Optional[str] = Field(None, description="Whether the volume is bootable")
    attached: bool = Field(False, description="Whether the volume is attached to a server")
    project_id: Optional[str] = Field(None, description="The project ID of the volume")
    policy_id: Optional[str] = Field(
        None,
        description="The ID of the policy the volume already belongs to",
    )


class AvailableVolumesResponse(BaseModel):
    count: int = Field(0, description="The number of available volumes")
    volumes: List[AvailableVolumeResponse] = Field(..., description="Available volumes list")
