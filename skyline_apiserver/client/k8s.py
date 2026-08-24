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
import json
import os
import ssl
import tempfile
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import urllib3
import yaml

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    if verify and os.path.exists(verify):
        verify = verify.replace("~", "").lstrip("/")
    return {
        "verify": verify or cluster.get("certificate-authority-data"),
        "client_cert": user.get("client-certificate")
        or user.get("client-certificate-data"),
        "client_key": user.get("client-key") or user.get("client-key-data"),
    }


def _normalize_server_url(server: str) -> str:
    if not server.startswith(("http://", "https://")):
        server = "https://" + server
    parsed = urlparse(server)
    hostname = parsed.hostname or ""
    return hostname + (":%s" % parsed.port if parsed.port else "")


def _has_credentials(config: Dict[str, Any]) -> bool:
    certs = _extract_certificates(config)
    return bool(_extract_token(config)) or bool(certs["client_cert"] and certs["client_key"])


def _build_headers(config: Dict[str, Any]) -> Dict[str, str]:
    token = _extract_token(config)
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _write_temp(content: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    return path


def _build_verify_and_cert(
    config: Dict[str, Any],
) -> Tuple[Any, Optional[Tuple[str, str]]]:
    certs = _extract_certificates(config)
    verify: Any = True
    ca = certs["verify"]
    if ca:
        try:
            content = base64.b64decode(ca.encode()).decode()
        except Exception:
            content = ca
        try:
            verify = _write_temp(content, ".crt")
        except Exception:
            verify = ca
    cert: Optional[Tuple[str, str]] = None
    client_cert = certs["client_cert"]
    client_key = certs["client_key"]
    if client_cert and client_key:
        try:
            cert_content = base64.b64decode(client_cert.encode()).decode()
            key_content = base64.b64decode(client_key.encode()).decode()
        except Exception:
            try:
                cert_content = base64.b64decode(client_cert.encode())
                key_content = base64.b64decode(client_key.encode())
            except Exception:
                cert_content = client_cert
                key_content = client_key
        try:
            cert_path = _write_temp(cert_content, ".pem")
            key_path = _write_temp(key_content, ".key")
            cert = (cert_path, key_path)
        except Exception:
            cert = None
    return verify, cert


def _build_pool_manager(
    verify: Any, cert: Optional[Tuple[str, str]], timeout: int = 15
) -> urllib3.PoolManager:
    pm_kwargs: Dict[str, Any] = {"timeout": timeout}
    if verify is False or verify is None:
        pm_kwargs["ssl_version"] = ssl.PROTOCOL_TLS
        pm_kwargs["cert_reqs"] = "CERT_NONE"
    elif isinstance(verify, str) and os.path.isfile(verify):
        pm_kwargs["ca_certs"] = verify
    if cert:
        pm_kwargs["cert_file"] = cert[0]
        pm_kwargs["key_file"] = cert[1]
    return urllib3.PoolManager(**pm_kwargs)


class _Response:
    """Minimal response wrapper to keep compatibility with existing callers."""

    def __init__(self, status: int, data: bytes, headers: Dict[str, str]) -> None:
        self.status_code = status
        self._data = data
        self.headers = headers

    def text(self) -> str:
        return self._data.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self._data)


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
    if not _has_credentials(config):
        raise ValueError(
            "Config yaml is invalid: no access token or client certificate found. "
            "A token or client certificate/key pair is required."
        )


def _api_base(server: str) -> str:
    return server.rstrip("/")


def _fetch(
    server: str, path: str, config: Dict[str, Any], timeout: int = 15
) -> _Response:
    url = _api_base(server) + path
    verify, cert = _build_verify_and_cert(config)
    headers = _build_headers(config)
    pm = _build_pool_manager(verify, cert, timeout)
    resp = pm.request("GET", url, headers=headers)
    return _Response(resp.status, resp.data, dict(resp.headers))


def _request(
    server: str,
    method: str,
    path: str,
    config: Dict[str, Any],
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> _Response:
    url = _api_base(server) + path
    verify, cert = _build_verify_and_cert(config)
    headers = _build_headers(config)
    body = json.dumps(json_body).encode() if json_body is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    pm = _build_pool_manager(verify, cert, timeout)
    resp = pm.request(method, url, headers=headers, body=body)
    return _Response(resp.status, resp.data, dict(resp.headers))


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
    """Return a token that can access the cluster dashboard.

    Prefers the token embedded in the config yaml. When the config authenticates
    with a client certificate instead, a ServiceAccount token is created inside
    the cluster by calling the Kubernetes API.
    """
    config = yaml.safe_load(config_yaml)
    server = _extract_server(config)
    existing = _extract_token(config)
    if existing:
        return existing
    certs = _extract_certificates(config)
    if not (certs["client_cert"] and certs["client_key"]):
        raise ValueError(
            "Config yaml is invalid: no access token or client certificate found."
        )
    return _create_dashboard_token(server, config)


def _create_dashboard_token(server: str, config: Dict[str, Any]) -> str:
    """Create a ServiceAccount + ClusterRoleBinding and fetch its token."""
    sa_name = DASHBOARD_SERVICE_ACCOUNT
    namespace = DASHBOARD_NAMESPACE
    crb_name = CLUSTER_ROLE_BINDING

    resp = _request(
        server,
        "GET",
        "/api/v1/namespaces/%s" % namespace,
        config,
    )
    if resp.status_code == 404:
        body = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": namespace},
        }
        resp = _request(
            server, "POST", "/api/v1/namespaces", config, json_body=body
        )
    if resp.status_code >= 400 and resp.status_code != 409:
        raise ValueError("Failed to create namespace: HTTP %s" % resp.status_code)

    resp = _request(
        server,
        "GET",
        "/api/v1/namespaces/%s/serviceaccounts/%s" % (namespace, sa_name),
        config,
    )
    if resp.status_code == 404:
        body = {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": sa_name, "namespace": namespace},
        }
        resp = _request(
            server,
            "POST",
            "/api/v1/namespaces/%s/serviceaccounts" % namespace,
            config,
            json_body=body,
        )
    if resp.status_code >= 400 and resp.status_code != 409:
        raise ValueError("Failed to create ServiceAccount: HTTP %s" % resp.status_code)

    resp = _request(
        server,
        "GET",
        "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings/%s" % crb_name,
        config,
    )
    if resp.status_code == 404:
        body = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": crb_name},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "cluster-admin",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": sa_name,
                    "namespace": namespace,
                }
            ],
        }
        resp = _request(
            server,
            "POST",
            "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
            config,
            json_body=body,
        )
    if resp.status_code >= 400 and resp.status_code != 409:
        raise ValueError(
            "Failed to create ClusterRoleBinding: HTTP %s" % resp.status_code
        )

    token_request = {
        "apiVersion": "authentication.k8s.io/v1",
        "kind": "TokenRequest",
        "metadata": {"name": sa_name, "namespace": namespace},
        "spec": {},
    }
    resp = _request(
        server,
        "POST",
        "/api/v1/namespaces/%s/serviceaccounts/%s/token"
        % (namespace, sa_name),
        config,
        json_body=token_request,
    )
    if resp.status_code >= 400 and resp.status_code != 409:
        raise ValueError("Failed to request ServiceAccount token: HTTP %s" % resp.status_code)
    data = resp.json()
    try:
        return data["status"]["token"]
    except (KeyError, TypeError):
        raise ValueError("Unexpected TokenRequest response: %s" % data)
