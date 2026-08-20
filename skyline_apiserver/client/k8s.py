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

import base64
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
import yaml

DASHBOARD_SERVICE_ACCOUNT = "kubernetes-dashboard-admin"
DASHBOARD_NAMESPACE = "kubernetes-dashboard"
CLUSTER_ROLE_BINDING = "kubernetes-dashboard-admin"


def _extract_server(config: Dict[str, Any]) -> str:
    try:
        return config["clusters"][0]["cluster"]["server"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(
            "Config yaml is invalid: clusters[0].cluster.server is missing."
        )


def _extract_token(config: Dict[str, Any]) -> Optional[str]:
    user = config.get("users", [{}])[0].get("user", {}) if config.get("users") else {}
    token = user.get("token")
    if token:
        return token
    token_file = user.get("tokenFile") or user.get("token-file")
    if token_file:
        with open(token_file, encoding="utf-8") as f:
            return f.read().strip()
    auth_provider = user.get("auth-provider", {})
    if auth_provider.get("config", {}).get("access-token"):
        return auth_provider["config"]["access-token"]
    return None


def _extract_certificates(config: Dict[str, Any]) -> Dict[str, Any]:
    cluster = (
        config.get("clusters", [{}])[0].get("cluster", {})
        if config.get("clusters")
        else {}
    )
    user = config.get("users", [{}])[0].get("user", {}) if config.get("users") else {}
    verify = cluster.get("certificate-authority")
    if verify:
        verify = verify.replace("~", "").lstrip("/")
    return {
        "verify": verify,
        "client_cert": user.get("client-certificate"),
        "client_key": user.get("client-key"),
    }


def _normalize_server_url(server: str) -> str:
    if not server.startswith(("http://", "https://")):
        server = "https://" + server
    parsed = urlparse(server)
    hostname = parsed.hostname or ""
    return hostname + (":%s" % parsed.port if parsed.port else "")


def _build_headers(config: Dict[str, Any]) -> Dict[str, str]:
    token = _extract_token(config)
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _build_verify_and_cert(
    config: Dict[str, Any],
) -> tuple:
    certs = _extract_certificates(config)
    verify: Any = True
    if certs["verify"]:
        try:
            verify = base64.b64decode(certs["verify"].encode()).decode()
            verify = _write_temp(verify)
        except Exception:
            verify = certs["verify"]
    cert = None
    if certs["client_cert"] and certs["client_key"]:
        cert = (certs["client_cert"], certs["client_key"])
    return verify, cert


def _write_temp(content: str) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".crt", delete=False) as f:
        f.write(content)
        return f.name


def validate_config(address: str, config_yaml: str) -> None:
    """Validate the config yaml matches the given address and is usable."""
    try:
        config = yaml.safe_load(config_yaml)
    except yaml.YAMLError as e:
        raise ValueError("Config yaml is not valid YAML: %s" % e)
    if not isinstance(config, dict):
        raise ValueError("Config yaml is invalid: root must be a mapping.")

    server = _extract_server(config)
    if _normalize_server_url(server) != _normalize_server_url(address):
        raise ValueError(
            "The server address in config yaml (%s) does not match the provided address (%s)."
            % (server, address)
        )
    if not _extract_token(config):
        raise ValueError(
            "Config yaml is invalid: no access token found. A token is required."
        )


def _api_base(server: str) -> str:
    return server.rstrip("/")


def _fetch(
    server: str, path: str, config: Dict[str, Any], timeout: int = 15
) -> httpx.Response:
    url = _api_base(server) + path
    verify, cert = _build_verify_and_cert(config)
    headers = _build_headers(config)
    with httpx.Client(
        verify=verify,
        cert=cert,
        timeout=timeout,
    ) as client:
        resp = client.get(url, headers=headers)
        return resp


async def check_connectivity(address: str, config_yaml: str) -> None:
    """Verify the config yaml can actually talk to the given cluster."""
    config = yaml.safe_load(config_yaml)
    server = _extract_server(config)
    try:
        resp = _fetch(server, "/version", config)
    except Exception as e:
        raise ValueError("Cannot connect to the cluster with the config yaml: %s" % e)
    if resp.status_code == 401:
        raise ValueError("The config yaml token is unauthorized (401).")
    if resp.status_code == 403:
        raise ValueError("The config yaml token is forbidden (403).")
    if resp.status_code >= 400:
        raise ValueError(
            "Cannot connect to the cluster with the config yaml (HTTP %s)."
            % resp.status_code
        )


def get_dashboard_token(config_yaml: str) -> str:
    """Return a token that can access the cluster dashboard."""
    config = yaml.safe_load(config_yaml)
    existing = _extract_token(config)
    if existing:
        return existing
    raise ValueError(
        "Config yaml is invalid: no access token found. A token is required."
    )
