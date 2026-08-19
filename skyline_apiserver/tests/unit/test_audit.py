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
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine

from skyline_apiserver import schemas
from skyline_apiserver.api import deps
from skyline_apiserver.config import CONF
from skyline_apiserver.db import api as db_api
from skyline_apiserver.db.models import METADATA, AuditLog, AuditLogDetail
from skyline_apiserver.main import app
from skyline_apiserver.schemas.login import Domain, Project, Role, User

pytestmark = pytest.mark.xdist_group(name="audit")

DOMAIN_ID = "default"
DOMAIN_NAME = "Default"
USER_ID = "u-123"
USER_NAME = "alice"


def make_profile(
    domain_id: str = DOMAIN_ID,
    domain_name: str = DOMAIN_NAME,
    user_id: str = USER_ID,
    user_name: str = USER_NAME,
) -> schemas.Profile:
    domain = Domain(id=domain_id, name=domain_name)
    return schemas.Profile(
        keystone_token="fake-keystone-token",
        region="RegionOne",
        exp=int(time.time()) + 3600,
        uuid="fake-uuid",
        project=Project(id="p-1", name="demo", domain=domain),
        user=User(id=user_id, name=user_name, domain=domain),
        roles=[Role(id="r1", name="member")],
        keystone_token_exp="2099-08-18T00:00:00Z",
        version="test",
    )


def main_values(log_id: str, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": log_id,
        "domain_id": DOMAIN_ID,
        "domain_name": DOMAIN_NAME,
        "project_id": "p-1",
        "project_name": "demo",
        "user_id": USER_ID,
        "user_name": USER_NAME,
        "module": "compute",
        "action": "delete_server",
        "targets": json.dumps([{"id": "srv-1", "name": "web-01", "type": "server"}]),
        "target_names": "web-01",
        "source_ip": "10.0.0.8",
        "request_result": "success",
    }
    values.update(overrides)
    return values


def detail_values(log_id: str, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "log_id": log_id,
        "trace_id": "req-1",
        "request_method": "DELETE",
        "request_path": "/api/openstack/servers/srv-1",
        "request_body": '{"server_id":"srv-1"}',
        "http_code": 200,
        "error_code": "",
        "error_message": "",
    }
    values.update(overrides)
    return values


@pytest.fixture
async def audit_tables(client) -> Any:
    engine = create_engine(CONF.default.database_url)
    METADATA.create_all(engine)
    yield engine
    with engine.begin() as conn:
        conn.execute(AuditLogDetail.delete())
        conn.execute(AuditLog.delete())
    engine.dispose()


@pytest.fixture
def auth_override() -> Any:
    profile = make_profile()
    app.dependency_overrides[deps.get_profile_update_jwt] = lambda: profile
    app.dependency_overrides[deps.get_profile_update_jwt_optional] = lambda: profile
    yield profile
    app.dependency_overrides.pop(deps.get_profile_update_jwt, None)
    app.dependency_overrides.pop(deps.get_profile_update_jwt_optional, None)


# ---------------------------------------------------------------------------
# db layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_audit_log_writes_both_tables_with_same_timestamp(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)

    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row is not None
    assert row["id"] == log_id
    assert row["created_at"] == now_ms
    assert row["updated_at"] == now_ms
    assert row["domain_id"] == DOMAIN_ID

    detail = await db_api.get_audit_log_detail(log_id)
    assert detail is not None
    assert detail["log_id"] == log_id
    assert detail["created_at"] == now_ms
    assert detail["updated_at"] == now_ms
    assert detail["trace_id"] == "req-1"


@pytest.mark.asyncio
async def test_update_audit_log_returns_not_found(audit_tables):
    result = await db_api.update_audit_log(
        log_id=uuid.uuid4().hex,
        domain_id=DOMAIN_ID,
        now_ms=int(time.time() * 1000),
        request_result="failed",
    )
    assert result == "not_found"


@pytest.mark.asyncio
async def test_update_audit_log_domain_mismatch_login_log_fallback(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id="", user_id=""),
        detail_values(log_id, request_path="/api/v1/login"),
        now_ms,
    )
    later_ms = now_ms + 5000

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=DOMAIN_ID,
        now_ms=later_ms,
        request_result="failed",
        http_code=500,
    )

    assert result == "updated"
    row = await db_api.get_audit_log(log_id, "")
    assert row["request_result"] == "failed"
    assert row["updated_at"] == later_ms
    detail = await db_api.get_audit_log_detail(log_id)
    assert detail["http_code"] == 500


@pytest.mark.asyncio
async def test_update_audit_log_domain_mismatch_non_login_still_not_found(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id=""),
        detail_values(log_id, request_path="/api/openstack/servers/srv-1"),
        now_ms,
    )

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=DOMAIN_ID,
        now_ms=now_ms + 5000,
        request_result="failed",
    )

    assert result == "not_found"


@pytest.mark.asyncio
async def test_update_audit_log_partial_update(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)
    later_ms = now_ms + 5000

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=DOMAIN_ID,
        now_ms=later_ms,
        request_result="failed",
        http_code=500,
    )

    assert result == "updated"
    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row["request_result"] == "failed"
    assert row["created_at"] == now_ms
    assert row["updated_at"] == later_ms

    detail = await db_api.get_audit_log_detail(log_id)
    assert detail["http_code"] == 500
    assert detail["error_code"] == ""
    assert detail["error_message"] == ""
    assert detail["created_at"] == now_ms
    assert detail["updated_at"] == later_ms


@pytest.mark.asyncio
async def test_update_audit_log_updates_user_fields(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_name="", user_id="", user_name=""),
        detail_values(log_id),
        now_ms,
    )
    later_ms = now_ms + 5000

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=DOMAIN_ID,
        now_ms=later_ms,
        domain_name=DOMAIN_NAME,
        user_id=USER_ID,
        user_name=USER_NAME,
    )

    assert result == "updated"
    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row["domain_name"] == DOMAIN_NAME
    assert row["user_id"] == USER_ID
    assert row["user_name"] == USER_NAME
    assert row["updated_at"] == later_ms


@pytest.mark.asyncio
async def test_update_audit_log_no_change_keeps_updated_at(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=DOMAIN_ID,
        now_ms=now_ms + 5000,
        request_result="success",
        http_code=200,
        error_code="",
        error_message="",
    )

    assert result == "no_change"
    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row["updated_at"] == now_ms
    detail = await db_api.get_audit_log_detail(log_id)
    assert detail["updated_at"] == now_ms


@pytest.mark.asyncio
async def test_update_audit_log_skips_missing_detail(audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)
    db = db_api.DB.get()
    assert db is not None
    async with db.transaction():
        await db.execute(AuditLogDetail.delete().where(AuditLogDetail.c.log_id == log_id))

    result = await db_api.update_audit_log(
        log_id=log_id,
        domain_id=DOMAIN_ID,
        now_ms=now_ms + 5000,
        http_code=500,
    )

    assert result == "no_change"
    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row["updated_at"] == now_ms


@pytest.mark.asyncio
async def test_list_audit_logs_filters_and_pagination(audit_tables):
    base_ms = int(time.time() * 1000)
    ids = [uuid.uuid4().hex for _ in range(4)]
    await db_api.create_audit_log(
        main_values(ids[0], module="compute", action="delete_server", request_result="success"),
        detail_values(ids[0]),
        base_ms,
    )
    await db_api.create_audit_log(
        main_values(ids[1], module="storage", action="create_volume", request_result="failed"),
        detail_values(ids[1]),
        base_ms + 1000,
    )
    await db_api.create_audit_log(
        main_values(
            ids[2],
            module="compute",
            action="create_server",
            request_result="success",
            user_name="Bob",
            targets=json.dumps([{"id": "srv-2", "name": "db-01", "type": "server"}]),
            project_id="p-2",
            project_name="prod",
        ),
        detail_values(ids[2]),
        base_ms + 2000,
    )
    await db_api.create_audit_log(
        main_values(ids[3], module="network", action="login", request_result="success"),
        detail_values(ids[3]),
        base_ms + 3000,
    )

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID)
    assert total == 4
    assert [r["id"] for r in rows] == [ids[3], ids[2], ids[1], ids[0]]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, module="compute")
    assert total == 2
    assert {r["id"] for r in rows} == {ids[0], ids[2]}

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, action="delete_server")
    assert total == 1
    assert rows[0]["id"] == ids[0]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, request_result="failed")
    assert total == 1
    assert rows[0]["id"] == ids[1]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, operator_name="BO")
    assert total == 1
    assert rows[0]["id"] == ids[2]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, target="DB-01")
    assert total == 1
    assert rows[0]["id"] == ids[2]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, target="srv-2")
    assert total == 1
    assert rows[0]["id"] == ids[2]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, project_id="p-2")
    assert total == 1
    assert rows[0]["id"] == ids[2]

    total, rows = await db_api.list_audit_logs(
        domain_id=DOMAIN_ID, start_time=base_ms + 1000, end_time=base_ms + 2000
    )
    assert total == 2
    assert {r["id"] for r in rows} == {ids[1], ids[2]}

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, page=2, size=2)
    assert total == 4
    assert [r["id"] for r in rows] == [ids[1], ids[0]]

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, page=3, size=2)
    assert total == 4
    assert rows == []


@pytest.mark.asyncio
async def test_list_audit_logs_10000_cap(audit_tables, monkeypatch):
    monkeypatch.setattr(db_api, "MAX_QUERY_LIMIT", 5)
    base_ms = int(time.time() * 1000)
    ids = [uuid.uuid4().hex for _ in range(6)]
    for i, log_id in enumerate(ids):
        await db_api.create_audit_log(
            main_values(log_id), detail_values(log_id), base_ms + i * 1000
        )

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID)
    assert total == 5
    assert len(rows) == 5

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, page=2, size=5)
    assert total == 5
    assert rows == []

    total, rows = await db_api.list_audit_logs(domain_id=DOMAIN_ID, page=1, size=10)
    assert total == 5
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# api layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_audit_log_endpoint(client, audit_tables, auth_override):
    payload = {
        "project_id": "8f3d7d2c",
        "project_name": "demo",
        "module": "compute",
        "action": "delete_server",
        "targets": [{"id": "srv-1", "name": "web-01", "type": "server"}],
        "trace_id": "req-123456",
        "request_method": "DELETE",
        "request_path": "/api/openstack/servers/srv-1",
        "request_body": '{"server_id":"srv-1"}',
        "request_result": "success",
    }

    response = await client.post(
        "/api/v1/audit/logs",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"]
    assert body["domain_id"] == DOMAIN_ID
    assert body["domain_name"] == DOMAIN_NAME
    assert body["user_id"] == USER_ID
    assert body["user_name"] == USER_NAME
    assert body["source_ip"] == "203.0.113.7"
    assert body["targets"] == [{"id": "srv-1", "name": "web-01", "type": "server"}]
    assert body["request_result"] == "success"

    row = await db_api.get_audit_log(body["id"], DOMAIN_ID)
    assert row is not None
    assert row["target_names"] == "web-01"
    detail = await db_api.get_audit_log_detail(body["id"])
    assert detail is not None
    assert detail["trace_id"] == "req-123456"


@pytest.mark.asyncio
async def test_create_audit_log_endpoint_missing_required_field(
    client, audit_tables, auth_override
):
    response = await client.post(
        "/api/v1/audit/logs",
        json={
            "project_name": "demo",
            "module": "compute",
            "action": "delete_server",
            "trace_id": "req-1",
            "request_method": "DELETE",
            "request_path": "/api/openstack/servers/srv-1",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_audit_log_endpoint(client, audit_tables, auth_override):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"request_result": "failed", "http_code": 500, "error_code": "E001"},
    )

    assert response.status_code == 204
    assert response.content == b""
    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row["request_result"] == "failed"
    detail = await db_api.get_audit_log_detail(log_id)
    assert detail["http_code"] == 500
    assert detail["error_code"] == "E001"


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_not_found(client, audit_tables, auth_override):
    response = await client.put(
        f"/api/v1/audit/logs/{uuid.uuid4().hex}",
        json={"request_result": "failed"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_login_log_domain_mismatch(
    client, audit_tables, auth_override
):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id="", user_id=""),
        detail_values(log_id, request_path="/api/v1/login"),
        now_ms,
    )

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"request_result": "failed", "http_code": 500},
    )

    assert response.status_code == 204
    row = await db_api.get_audit_log(log_id, "")
    assert row["request_result"] == "failed"
    detail = await db_api.get_audit_log_detail(log_id)
    assert detail["http_code"] == 500


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_non_login_domain_mismatch(
    client, audit_tables, auth_override
):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id=""),
        detail_values(log_id),
        now_ms,
    )

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"request_result": "failed"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_backfills_user_fields(
    client, audit_tables, auth_override
):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id="", domain_name="", user_id="", user_name=""),
        detail_values(log_id, request_path="/api/v1/login"),
        now_ms,
    )

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"request_result": "success"},
    )

    assert response.status_code == 204
    row = await db_api.get_audit_log(log_id, "")
    assert row["domain_id"] == ""
    assert row["domain_name"] == DOMAIN_NAME
    assert row["user_id"] == USER_ID
    assert row["user_name"] == USER_NAME


# ---------------------------------------------------------------------------
# api layer - update login/logout without token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_without_token_logout(client, audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id="", user_id=""),
        detail_values(log_id, request_path="/api/v1/logout"),
        now_ms,
    )

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"module": "auth", "action": "logout", "request_result": "success"},
    )

    assert response.status_code == 204
    row = await db_api.get_audit_log(log_id, "")
    assert row["request_result"] == "success"


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_without_token_login(client, audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id="", user_id=""),
        detail_values(log_id, request_path="/api/v1/login"),
        now_ms,
    )

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"module": "auth", "action": "login", "request_result": "failed"},
    )

    assert response.status_code == 204
    row = await db_api.get_audit_log(log_id, "")
    assert row["request_result"] == "failed"


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_without_token_not_allowed(client, audit_tables):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, domain_id=""),
        detail_values(log_id),
        now_ms,
    )

    response = await client.put(
        f"/api/v1/audit/logs/{log_id}",
        json={"action": "delete_server", "request_result": "failed"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_audit_log_endpoint_empty_body(client, audit_tables, auth_override):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)

    response = await client.put(f"/api/v1/audit/logs/{log_id}", json={})

    assert response.status_code == 204
    assert response.content == b""
    row = await db_api.get_audit_log(log_id, DOMAIN_ID)
    assert row["updated_at"] == now_ms


@pytest.mark.asyncio
async def test_list_audit_logs_endpoint(client, audit_tables, auth_override):
    base_ms = int(time.time() * 1000)
    log_id = uuid.uuid4().hex
    await db_api.create_audit_log(
        main_values(log_id, module="compute", request_result="failed"),
        detail_values(log_id),
        base_ms,
    )

    response = await client.get(
        "/api/v1/audit/logs",
        params={"module": "compute", "page": 1, "size": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["size"] == 10
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == log_id
    assert body["items"][0]["request_result"] == "failed"
    assert body["items"][0]["targets"] == [{"id": "srv-1", "name": "web-01", "type": "server"}]
    assert "trace_id" not in body["items"][0]


@pytest.mark.asyncio
async def test_list_audit_logs_endpoint_invalid_time_range(client, audit_tables, auth_override):
    response = await client.get(
        "/api/v1/audit/logs",
        params={"start_time": 2000, "end_time": 1000},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_audit_logs_endpoint_invalid_pagination(client, audit_tables, auth_override):
    response = await client.get("/api/v1/audit/logs", params={"size": 200})
    assert response.status_code == 422
    response = await client.get("/api/v1/audit/logs", params={"page": 0})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_audit_log_detail_endpoint(client, audit_tables, auth_override):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(
        main_values(log_id, request_result="failed"),
        detail_values(log_id, http_code=500, error_code="E001"),
        now_ms,
    )

    response = await client.get(f"/api/v1/audit/logs/{log_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == log_id
    assert body["request_result"] == "failed"
    assert body["trace_id"] == "req-1"
    assert body["request_method"] == "DELETE"
    assert body["request_path"] == "/api/openstack/servers/srv-1"
    assert body["request_body"] == '{"server_id":"srv-1"}'
    assert body["http_code"] == 500
    assert body["error_code"] == "E001"
    assert body["targets"] == [{"id": "srv-1", "name": "web-01", "type": "server"}]


@pytest.mark.asyncio
async def test_get_audit_log_detail_endpoint_not_found(client, audit_tables, auth_override):
    response = await client.get(f"/api/v1/audit/logs/{uuid.uuid4().hex}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_audit_log_detail_endpoint_missing_detail(client, audit_tables, auth_override):
    log_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    await db_api.create_audit_log(main_values(log_id), detail_values(log_id), now_ms)
    db = db_api.DB.get()
    assert db is not None
    async with db.transaction():
        await db.execute(AuditLogDetail.delete().where(AuditLogDetail.c.log_id == log_id))

    response = await client.get(f"/api/v1/audit/logs/{log_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# api layer - login/logout without token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_audit_log_endpoint_without_token_login(client, audit_tables):
    payload = {
        "project_id": "-",
        "project_name": "-",
        "module": "auth",
        "action": "login",
        "targets": [{"type": "system", "name": "admin"}],
        "trace_id": "req-da640888-9845-401e-a982-cd1f28b2cc24",
        "request_method": "POST",
        "request_path": "/api/openstack/skyline/api/v1/login",
        "request_body": (
            '{"domain":"Default","password":"******",' '"region":"RegionOne","username":"admin"}'
        ),
        "request_result": "pending",
    }

    response = await client.post(
        "/api/v1/audit/logs",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"]
    assert body["domain_id"] == ""
    assert body["domain_name"] == "Default"
    assert body["user_id"] == ""
    assert body["user_name"] == "admin"
    assert body["source_ip"] == "203.0.113.9"
    assert body["module"] == "auth"
    assert body["action"] == "login"
    assert body["request_result"] == "pending"

    row = await db_api.get_audit_log(body["id"], "")
    assert row is not None
    assert row["domain_name"] == "Default"
    assert row["user_name"] == "admin"


@pytest.mark.asyncio
async def test_create_audit_log_endpoint_without_token_login_from_request_body(
    client, audit_tables
):
    payload = {
        "project_id": "-",
        "project_name": "-",
        "module": "auth",
        "action": "login",
        "trace_id": "req-login-1",
        "request_method": "POST",
        "request_path": "/api/v1/login",
        "request_result": "failed",
        "http_code": 401,
        "error_code": "E001",
        "error_message": "Invalid credentials",
        "request_body": (
            '{"domain":"Default","password":"******",'
            '"region":"RegionOne","username":"admin33333"}'
        ),
    }

    response = await client.post("/api/v1/audit/logs", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["domain_id"] == ""
    assert body["domain_name"] == "Default"
    assert body["user_id"] == ""
    assert body["user_name"] == "admin33333"

    row = await db_api.get_audit_log(body["id"], "")
    assert row is not None
    assert row["user_name"] == "admin33333"


@pytest.mark.asyncio
async def test_create_audit_log_endpoint_without_token_login_invalid_request_body(
    client, audit_tables
):
    payload = {
        "project_id": "-",
        "project_name": "-",
        "module": "auth",
        "action": "login",
        "trace_id": "req-login-2",
        "request_method": "POST",
        "request_path": "/api/v1/login",
        "request_result": "failed",
        "request_body": "not-a-json",
    }

    response = await client.post("/api/v1/audit/logs", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["domain_id"] == ""
    assert body["domain_name"] == ""
    assert body["user_id"] == ""
    assert body["user_name"] == ""


@pytest.mark.asyncio
async def test_create_audit_log_endpoint_without_token_logout(client, audit_tables):
    payload = {
        "project_id": "-",
        "project_name": "-",
        "module": "auth",
        "action": "logout",
        "trace_id": "req-logout-1",
        "request_method": "POST",
        "request_path": "/api/v1/logout",
        "request_result": "success",
    }

    response = await client.post("/api/v1/audit/logs", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "logout"
    assert body["domain_id"] == ""
    assert body["user_id"] == ""


@pytest.mark.asyncio
async def test_create_audit_log_endpoint_without_token_not_allowed(client, audit_tables):
    payload = {
        "project_id": "8f3d7d2c",
        "project_name": "demo",
        "module": "compute",
        "action": "delete_server",
        "targets": [{"id": "srv-1", "name": "web-01", "type": "server"}],
        "trace_id": "req-123456",
        "request_method": "DELETE",
        "request_path": "/api/openstack/servers/srv-1",
        "request_result": "success",
    }

    response = await client.post("/api/v1/audit/logs", json=payload)

    assert response.status_code == 401
