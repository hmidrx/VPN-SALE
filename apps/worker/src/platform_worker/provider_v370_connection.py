"""Shared construction of authenticated, bounded 3x-ui v3.7.0 clients."""

from __future__ import annotations

from typing import cast

from panel_adapters.sanaei_3x_ui_v370 import (
    HttpxSanaei3xUiV370Transport,
    Sanaei3xUiV370Client,
)
from vpnsale_domain.providers import PanelInstance


async def connect_v370(
    panel: PanelInstance,
    endpoint_origin: str,
    credential: dict[str, object],
) -> tuple[HttpxSanaei3xUiV370Transport, Sanaei3xUiV370Client]:
    auth_mode = credential.get("auth_mode")
    if auth_mode == "bearer_token" and isinstance(credential.get("bearer_token"), str):
        token = cast(str, credential["bearer_token"])
        transport = await HttpxSanaei3xUiV370Transport.connect(
            endpoint_origin,
            base_path=panel.base_path,
            bearer_token=token,
            verify_tls=panel.tls_policy.verify_tls,
        )
        return transport, Sanaei3xUiV370Client(
            transport,
            base_path=panel.base_path,
            bearer_token=token,
        )
    if (
        auth_mode == "username_password"
        and isinstance(credential.get("username"), str)
        and isinstance(credential.get("password"), str)
    ):
        transport = await HttpxSanaei3xUiV370Transport.connect(
            endpoint_origin,
            base_path=panel.base_path,
            username=cast(str, credential["username"]),
            password=cast(str, credential["password"]),
            verify_tls=panel.tls_policy.verify_tls,
        )
        return transport, Sanaei3xUiV370Client(
            transport,
            base_path=panel.base_path,
            session_csrf_token=transport.session_csrf_token,
        )
    raise ValueError("provider credential invalid")
