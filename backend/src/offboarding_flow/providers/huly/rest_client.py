"""Huly REST 客户端 — 7 个 endpoint + Account RPC 封装。

复刻 @hcengineering/api-client/src/rest/rest.ts 的 RestClient（约 280 行 → 200 行 Python）。

endpoint 列表（与 TS RestClient 1:1 对应）：
- Account RPC（独立服务，nginx /_accounts）
  - login              {email, password} → {token}
  - selectWorkspace    {workspaceUrl}    → {token, endpoint, workspace, ...}
- Transactor REST（nginx /_transactor → huly-transactor-1）
  - GET  /api/v1/account/{ws}                              → Account
  - GET  /api/v1/find-all/{ws}?class=&query=&options=     → FindResult
  - POST /api/v1/tx/{ws}                                   → TxResult
  - GET  /api/v1/load-model/{ws}?full=                     → Tx[]
  - GET  /api/v1/search-fulltext/{ws}?query=&...           → SearchResult
  - POST /api/v1/request/{domain}/{ws}                     → DomainResult
  - POST /api/v1/ensure-person/{ws}                        → {uuid, socialId, localPerson}

接口与 sidecar 调用对齐 — Provider 直调 RestClient.find_one / tx 等即可。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountInfo:
    """Huly /api/v1/account 返回值 — 业务关心的子集。"""

    uuid: str  # personUuid
    social_ids: tuple[str, ...]  # PersonId list，按 socialIds 顺序
    primary_social_id: str  # 主社交身份（modifiedBy 默认用这个）
    raw: dict[str, Any]  # 完整原始 dict（debugging）


class HulyRestError(RuntimeError):
    """Huly REST/RPC 调用失败统一异常。"""


class HulyRestClient:
    """Huly REST 客户端 — 复刻 TS RestClient 的所有 HTTP 行为。

    生命周期：
    1. login(email, password)            → token
    2. select_workspace(token, ws_url)   → workspace_token + endpoint
    3. 之后所有 REST 调用用 workspace_token 注入 Authorization Bearer
    """

    def __init__(
        self,
        *,
        accounts_url: str,
        workspace_token: str | None = None,
        workspace_uuid: str | None = None,
        endpoint: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._accounts_url = accounts_url.rstrip("/")
        self._workspace_token: str | None = workspace_token
        self._workspace_uuid: str | None = workspace_uuid
        # endpoint 是 ws:// 或 wss://，REST 调用要 swap http(s)
        self._endpoint_http: str | None = (
            endpoint.replace("ws://", "http://").replace("wss://", "https://") if endpoint else None
        )
        self._timeout = timeout

    @property
    def workspace_uuid(self) -> str:
        if self._workspace_uuid is None:
            raise HulyRestError("未 selectWorkspace — 先调 connect_huly() 拿 workspace_token")
        return self._workspace_uuid

    @property
    def endpoint_http(self) -> str:
        if self._endpoint_http is None:
            raise HulyRestError("未 selectWorkspace — endpoint 未知")
        return self._endpoint_http

    @property
    def workspace_token(self) -> str:
        if self._workspace_token is None:
            raise HulyRestError("未 selectWorkspace — workspace_token 未知")
        return self._workspace_token

    # ------------------------------------------------------------------ #
    # Account RPC (login / selectWorkspace) — 独立 nginx /_accounts
    # ------------------------------------------------------------------ #

    async def login(self, email: str, password: str) -> str:
        """登录 → 返回原始 user token（未 select workspace）。"""
        result = await self._rpc("login", {"email": email, "password": password})
        token = result.get("token")
        if not token:
            raise HulyRestError(f"login 返回缺 token: {result!r}")
        return cast(str, token)

    async def select_workspace(
        self,
        token: str,
        workspace_url: str,
    ) -> dict[str, Any]:
        """selectWorkspace → 返回 {token, endpoint, workspace(uuid), workspaceUrl, ...}。

        副作用：缓存 workspace_token / workspace_uuid / endpoint_http 到 self。
        """
        ws = await self._rpc("selectWorkspace", {"workspaceUrl": workspace_url}, token=token)
        if not isinstance(ws, dict):
            raise HulyRestError(f"selectWorkspace 返回非 dict: {ws!r}")
        ws_token = ws.get("token")
        ws_uuid = ws.get("workspace") or ws.get("workspaceUuid")
        endpoint = ws.get("endpoint")
        if not ws_token or not ws_uuid or not endpoint:
            raise HulyRestError(f"selectWorkspace 返回缺字段: {ws!r}")
        self._workspace_token = cast(str, ws_token)
        self._workspace_uuid = cast(str, ws_uuid)
        self._endpoint_http = (
            cast(str, endpoint).replace("ws://", "http://").replace("wss://", "https://")
        )
        return ws

    async def _rpc(
        self,
        method: str,
        params: Any,
        *,
        token: str | None = None,
    ) -> Any:
        """内部 helper：POST {accounts_url} {method, params}。"""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                self._accounts_url,
                json={"method": method, "params": params},
                headers=headers,
            )
        if r.status_code != 200:
            raise HulyRestError(f"Account RPC {method} HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        if body.get("error"):
            raise HulyRestError(f"Account RPC {method} 业务失败: {body['error']!r}")
        return body.get("result")

    # ------------------------------------------------------------------ #
    # Transactor REST (workspace-scoped)
    # ------------------------------------------------------------------ #

    async def get_account(self) -> AccountInfo:
        """GET /api/v1/account/{ws} → AccountInfo。"""
        data = await self._get_json(f"/api/v1/account/{self.workspace_uuid}")
        if not isinstance(data, dict):
            raise HulyRestError(f"get_account 返回非 dict: {data!r}")
        social_ids_raw = data.get("socialIds") or []
        if not isinstance(social_ids_raw, list):
            raise HulyRestError(f"get_account socialIds 非 list: {social_ids_raw!r}")
        primary = data.get("primarySocialId") or (social_ids_raw[0] if social_ids_raw else None)
        if not primary:
            raise HulyRestError(f"get_account 缺 primarySocialId: {data!r}")
        return AccountInfo(
            uuid=str(data.get("uuid") or ""),
            social_ids=tuple(str(s) for s in social_ids_raw),
            primary_social_id=str(primary),
            raw=data,
        )

    async def find_all(
        self,
        _class: str,
        query: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/find-all/{ws}?class=&query=&options= → list of docs。

        TS 返回 {dataType: TotalArray, total, lookupMap, value: [...]} —
        Python 抽 value 数组返回。failure → 抛 HulyRestError。
        """
        params: dict[str, str] = {"class": _class}
        if query:
            params["query"] = json.dumps(query, separators=(",", ":"))
        if options:
            params["options"] = json.dumps(options, separators=(",", ":"))
        data = await self._get_json(f"/api/v1/find-all/{self.workspace_uuid}", params=params)
        # TS rest.ts extractJson 走 rpcJSONReceiver — TotalArray 走 Object.assign(value, ...)
        # Python 解 JSON 得 {dataType, total, value}，统一抽 value
        if isinstance(data, dict):
            value = data.get("value")
            if isinstance(value, list):
                return cast(list[dict[str, Any]], value)
            raise HulyRestError(f"find_all 返回 dict 缺 value: {data!r}")
        if isinstance(data, list):
            return cast(list[dict[str, Any]], data)
        raise HulyRestError(f"find_all 返回非预期: {type(data).__name__}")

    async def find_one(
        self,
        _class: str,
        query: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """find_all + limit 1 → 第一个 doc 或 None。"""
        merged_options = dict(options or {})
        merged_options["limit"] = 1
        docs = await self.find_all(_class, query, merged_options)
        return docs[0] if docs else None

    async def tx(self, tx_obj: dict[str, Any]) -> Any:
        """POST /api/v1/tx/{ws} body=Tx object → TxResult。

        TS RestClient.tx 返回 server 端的 TxResult（通常是 [] 或对象）。
        Python 直接转发 server 响应（caller 自行解读）。
        """
        return await self._post_json(f"/api/v1/tx/{self.workspace_uuid}", body=tx_obj)

    async def ensure_person(
        self,
        social_type: str,
        social_value: str,
        first_name: str,
        last_name: str,
    ) -> dict[str, Any]:
        """POST /api/v1/ensure-person/{ws} → {uuid, socialId, localPerson}。"""
        body = {
            "socialType": social_type,
            "socialValue": social_value,
            "firstName": first_name,
            "lastName": last_name,
        }
        result = await self._post_json(f"/api/v1/ensure-person/{self.workspace_uuid}", body=body)
        if not isinstance(result, dict):
            raise HulyRestError(f"ensure_person 返回非 dict: {result!r}")
        return cast(dict[str, Any], result)

    # ------------------------------------------------------------------ #
    # 低层 HTTP helper
    # ------------------------------------------------------------------ #

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.workspace_token}",
            "accept-encoding": "gzip",
            # TS RestClient 默认 snappy + gzip；Python httpx 默认走 gzip
        }

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.endpoint_http}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(url, params=params, headers=self._auth_headers())
        if r.status_code != 200:
            raise HulyRestError(f"GET {path} HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except Exception as e:
            raise HulyRestError(f"GET {path} 响应非 JSON: {e}") from e

    async def _post_json(
        self,
        path: str,
        *,
        body: dict[str, Any],
    ) -> Any:
        url = f"{self.endpoint_http}{path}"
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(url, json=body, headers=headers)
        if r.status_code != 200:
            raise HulyRestError(
                f"POST {path} HTTP {r.status_code}: {r.text[:300]} (body={json.dumps(body)[:200]})"
            )
        # tx 端点可能返回空 array / 单值，统一 r.json()
        try:
            return r.json()
        except Exception:
            return r.text  # 不是 JSON 时返回原始文本（如空）
