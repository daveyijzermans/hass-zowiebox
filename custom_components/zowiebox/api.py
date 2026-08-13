"""Async API client for ZowieTek ZowieBox encoder/decoders.

Protocol: HTTP POST to /<endpoint>?option=getinfo|setinfo&login_check_flag=1
with a JSON body {"group": ..., "opt": ..., "data": {...}}. Documented in the
ZowieTek API v1.0 PDF; quirks discovered against live boxes:

- get_workmode_id returns workmode_id at the TOP level, not under data.
- Every /streamplay call (ndi_find, ndi_get_all, get_decoder_state, ...) is
  rejected with rsp "workmode is not support!" (status 00004) while the box
  is in ENCODER mode — NDI source enumeration must come from mDNS instead.
- rsp is "succeed" on most calls but "success" on some; status "00000" is OK
  and "00010" is the OK status for reboot.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=10)

OK_STATUSES = {"00000", "00010"}
WORKMODE_UNSUPPORTED_STATUS = "00004"


class ZowieboxError(Exception):
    """Base error talking to a ZowieBox."""


class ZowieboxConnectionError(ZowieboxError):
    """Box unreachable / transport error."""


class ZowieboxWorkmodeError(ZowieboxError):
    """Call not valid in the box's current work mode (status 00004)."""


class ZowieboxClient:
    """Thin async client around the {group, opt} POST protocol."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._host = host
        self._session = session

    @property
    def host(self) -> str:
        return self._host

    async def _post(
        self,
        endpoint: str,
        option: str,
        group: str,
        opt: str,
        data: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"http://{self._host}/{endpoint}?option={option}&login_check_flag=1"
        body: dict[str, Any] = {"group": group, "opt": opt}
        if data is not None:
            body["data"] = data
        if extra:
            body.update(extra)
        # The box's embedded HTTP server drops idle keep-alive connections
        # ("Server disconnected"), so force fresh connections and retry once.
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                async with self._session.post(
                    url,
                    json=body,
                    timeout=TIMEOUT,
                    headers={"Connection": "close"},
                ) as resp:
                    payload = await resp.json(content_type=None)
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_err = err
                if attempt == 0:
                    await asyncio.sleep(0.5)
        else:
            raise ZowieboxConnectionError(f"{self._host}: {last_err}") from last_err
        if not isinstance(payload, dict):
            raise ZowieboxError(f"{self._host}: unexpected response {payload!r}")
        status = str(payload.get("status", ""))
        if status == WORKMODE_UNSUPPORTED_STATUS:
            raise ZowieboxWorkmodeError(
                f"{self._host}: {group}/{opt} not supported in current work mode"
            )
        if status not in OK_STATUSES:
            raise ZowieboxError(
                f"{self._host}: {group}/{opt} failed: "
                f"status={status} rsp={payload.get('rsp')!r}"
            )
        return payload

    # -- work mode -----------------------------------------------------

    async def get_workmode_id(self) -> int:
        """0 = Encoder, 1 = Decoder. Field sits at the response top level."""
        payload = await self._post(
            "system", "getinfo", "workmode", "get_workmode_id"
        )
        workmode = payload.get("workmode_id")
        if workmode is None:
            workmode = (payload.get("data") or {}).get("workmode_id")
        if workmode is None:
            raise ZowieboxError(f"{self._host}: no workmode_id in response")
        return int(workmode)

    async def set_workmode(self, workmode_id: int) -> None:
        await self._post(
            "system",
            "setinfo",
            "workmode",
            "change_workmode",
            data={"workmode_id": workmode_id},
        )

    # -- video / HDMI ---------------------------------------------------

    async def get_input_info(self) -> dict[str, Any]:
        """HDMI input signal: hdmi_signal, audio_signal, width/height/framerate/desc."""
        payload = await self._post("video", "getinfo", "hdmi", "get_input_info")
        return payload.get("data") or {}

    async def get_output_info(self) -> dict[str, Any]:
        payload = await self._post("video", "getinfo", "hdmi", "get_output_info")
        return payload.get("data") or {}

    async def set_output_info(self, data: dict[str, Any]) -> None:
        # skip_check_mpp mirrors the box's own web UI when re-applying output
        # config around a work-mode change.
        await self._post(
            "video",
            "setinfo",
            "hdmi",
            "set_output_info",
            data=data,
            extra={"skip_check_mpp": 1},
        )

    async def get_ndi_info(self) -> dict[str, Any]:
        """NDI publish config; data.machinename is the box's own NDI name."""
        payload = await self._post("video", "getinfo", "ndi", "get_ndi_info")
        return payload.get("data") or {}

    # -- decode (only valid in Decoder mode) ----------------------------

    async def get_decoder_state(self) -> int | None:
        payload = await self._post(
            "streamplay", "getinfo", "streamplay", "get_decoder_state"
        )
        return (payload.get("data") or {}).get("decoder_state")

    async def ndi_find(self) -> None:
        """Kick the box's own NDI discovery (feeds ndi_get_all)."""
        await self._post("streamplay", "setinfo", "streamplay_ndi", "ndi_find")

    async def ndi_get_all(self) -> list[dict[str, Any]]:
        """Box-side NDI source list. The ACTIVE subscription is the entry with
        streamplay_status == 1 — ndi_get_recv_config never carries the
        subscribed name, so this list is the only truthful status source."""
        payload = await self._post(
            "streamplay", "getinfo", "streamplay_ndi", "ndi_get_all"
        )
        data = payload.get("data")
        return data if isinstance(data, list) else []

    async def ndi_recv(self, ndi_name: str) -> None:
        await self._post(
            "streamplay",
            "setinfo",
            "streamplay_ndi",
            "ndi_recv",
            data={"ndi_name": ndi_name},
        )

    # -- system ----------------------------------------------------------

    async def get_lan_info(self) -> dict[str, Any]:
        """LAN config; data.mac is the stable unique id."""
        payload = await self._post("network", "getinfo", "lan", "get_lan_info")
        return payload.get("data") or {}

    async def reboot(self) -> None:
        await self._post(
            "system",
            "setinfo",
            "syscontrol",
            "set_reboot_info",
            data={"command": "reboot"},
        )
