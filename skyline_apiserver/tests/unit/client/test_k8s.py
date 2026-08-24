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
from typing import Any, Dict, Optional, Type

import pytest
import yaml

from skyline_apiserver.client import k8s
from skyline_apiserver.tests.models import ArgumentData, TestData


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


CERT_BODY = "-----BEGIN CERTIFICATE-----\nMIIFakeCert\n-----END CERTIFICATE-----\n"
KEY_BODY = "-----BEGIN RSA PRIVATE KEY-----\nMIIFakeKey\n-----END RSA PRIVATE KEY-----\n"
CA_BODY = "-----BEGIN CERTIFICATE-----\nMIIFakeCa\n-----END CERTIFICATE-----\n"


def build_kubeconfig(
    server: str = "https://10.127.247.182:6443",
    with_ca: bool = True,
    with_token: bool = False,
    with_cert: bool = True,
) -> Dict[str, Any]:
    cluster: Dict[str, Any] = {"server": server}
    if with_ca:
        cluster["certificate-authority-data"] = _b64(CA_BODY)
    user: Dict[str, Any] = {}
    if with_token:
        user["token"] = "existing-token"
    if with_cert:
        user["client-certificate-data"] = _b64(CERT_BODY)
        user["client-key-data"] = _b64(KEY_BODY)
    return {
        "apiVersion": "v1",
        "clusters": [{"cluster": cluster, "name": "kubekey"}],
        "contexts": [
            {
                "context": {"cluster": "kubekey", "user": "kubernetes-admin"},
                "name": "kubernetes-admin@kubekey",
            }
        ],
        "current-context": "kubernetes-admin@kubekey",
        "kind": "Config",
        "preferences": {},
        "users": [{"name": "kubernetes-admin", "user": user}],
    }


class TestValidateConfig:
    @pytest.mark.ddt(
        TestData(
            arguments=("config", "address", "expected_raises"),
            argument_data_set=[
                ArgumentData(
                    id="cert_config_matches",
                    values=(build_kubeconfig(), "https://10.127.247.182:6443", None),
                ),
                ArgumentData(
                    id="token_config_matches",
                    values=(
                        build_kubeconfig(with_cert=False, with_token=True),
                        "10.127.247.182:6443",
                        None,
                    ),
                ),
                ArgumentData(
                    id="cert_config_address_mismatch",
                    values=(build_kubeconfig(), "https://10.0.0.1:6443", ValueError),
                ),
                ArgumentData(
                    id="no_credentials",
                    values=(
                        build_kubeconfig(with_cert=False),
                        "https://10.127.247.182:6443",
                        ValueError,
                    ),
                ),
            ],
        ),
    )
    def test_validate_config(
        self,
        config: Dict[str, Any],
        address: str,
        expected_raises: Optional[Type[Exception]],
    ) -> None:
        yaml_text = yaml.safe_dump(config)
        if expected_raises is None:
            k8s.validate_config(address, yaml_text)
        else:
            with pytest.raises(expected_raises):
                k8s.validate_config(address, yaml_text)

    def test_validate_config_invalid_yaml(self) -> None:
        with pytest.raises(ValueError):
            k8s.validate_config("https://10.127.247.182:6443", "{{")


class TestCertificates:
    def test_build_verify_and_cert_from_b64_data(self) -> None:
        verify, cert = k8s._build_verify_and_cert(build_kubeconfig())
        assert isinstance(verify, str)
        with open(verify, encoding="utf-8") as f:
            assert "BEGIN CERTIFICATE" in f.read()
        assert cert is not None
        cert_path, key_path = cert
        with open(cert_path, encoding="utf-8") as f:
            assert "BEGIN CERTIFICATE" in f.read()
        with open(key_path, encoding="utf-8") as f:
            assert "BEGIN RSA PRIVATE KEY" in f.read()


class TestDashboardToken:
    def test_prefers_existing_token(self) -> None:
        doc = build_kubeconfig(with_cert=False, with_token=True)
        assert k8s.get_dashboard_token(yaml.safe_dump(doc)) == "existing-token"

    def test_requires_credential(self) -> None:
        doc = build_kubeconfig(with_cert=False)
        with pytest.raises(ValueError):
            k8s.get_dashboard_token(yaml.safe_dump(doc))
