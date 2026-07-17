"""Proton HTTP client: requests, auth, token refresh."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from proton_cli.proton.errors import APIError, ErrUnauthorized, HumanVerificationError, NetworkError

DEFAULT_BASE_URL = "https://mail.proton.me/api"
DEFAULT_APP_VERSION = "Other"
DEFAULT_USER_AGENT = "proton-cli/dev"
MAX_RATE_LIMIT_WAIT = 30.0

HVResolver = Callable[[HumanVerificationError], tuple[str, str]]


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] | None = None
    body: Any = None
    content_type: str = ""
    hv_token: str = ""
    hv_type: str = ""


@dataclass
class Response:
    status: int
    body: bytes
    retry_after: str = ""


@dataclass
class Client:
    base_url: str = DEFAULT_BASE_URL
    app_version: str = DEFAULT_APP_VERSION
    user_agent: str = DEFAULT_USER_AGENT
    profile: str = "default"
    _uid: str = ""
    _access: str = ""
    _refresh: str = ""
    _salted_key_pass: str = ""
    _enc_key_blob: str = ""
    _hv_resolver: HVResolver | None = None
    _persist: Callable[[], None] | None = None
    _client: httpx.Client = field(default_factory=httpx.Client)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def new(
        cls,
        *,
        base_url: str = "",
        app_version: str = "",
        user_agent: str = "",
        profile: str = "default",
        timeout: float = 300.0,
    ) -> Client:
        return cls(
            base_url=base_url or DEFAULT_BASE_URL,
            app_version=app_version or DEFAULT_APP_VERSION,
            user_agent=user_agent or DEFAULT_USER_AGENT,
            profile=profile,
            _client=httpx.Client(timeout=timeout),
        )

    def set_tokens(self, uid: str, access: str, refresh: str) -> None:
        with self._lock:
            self._uid, self._access, self._refresh = uid, access, refresh

    def tokens(self) -> tuple[str, str, str]:
        with self._lock:
            return self._uid, self._access, self._refresh

    def salted_key_pass(self) -> str:
        with self._lock:
            return self._salted_key_pass

    def set_salted_key_pass(self, value: str) -> None:
        with self._lock:
            self._salted_key_pass = value

    def enc_key_blob(self) -> str:
        with self._lock:
            return self._enc_key_blob

    def set_enc_key_blob(self, value: str) -> None:
        with self._lock:
            self._enc_key_blob = value

    def set_persist_hook(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._persist = fn

    def persist(self) -> None:
        with self._lock:
            fn = self._persist
        if fn:
            fn()

    def set_hv_resolver(self, resolver: HVResolver | None) -> None:
        with self._lock:
            self._hv_resolver = resolver

    def get_hv_resolver(self) -> HVResolver | None:
        with self._lock:
            return self._hv_resolver

    def _get_hv_resolver(self) -> HVResolver | None:
        with self._lock:
            return self._hv_resolver

    def login(self, username: str, password: str, totp: str = "") -> None:
        from proton_cli.proton.auth import login as srp_login

        srp_login(self, username, password, totp)

    def do(self, req: Request) -> Response:
        resp = self._do_once(req)
        if resp.status == 401:
            if self._refresh_auth():
                self.persist()
                resp = self._do_once(req)
            else:
                raise ErrUnauthorized
        if resp.status == 429:
            delay = _retry_after_seconds(resp.retry_after)
            if delay and delay <= MAX_RATE_LIMIT_WAIT:
                time.sleep(delay)
                resp = self._do_once(req)
        if 200 <= resp.status < 300:
            return resp
        hv_err, api_err = _classify_error(resp.status, resp.body)
        if hv_err and not req.hv_token:
            resolver = self._get_hv_resolver()
            if resolver:
                token, kind = resolver(hv_err)
                if token:
                    retry = Request(
                        method=req.method,
                        path=req.path,
                        query=req.query,
                        body=req.body,
                        content_type=req.content_type,
                        hv_token=token,
                        hv_type=kind,
                    )
                    return self.do(retry)
        if hv_err:
            raise hv_err
        raise api_err

    def decode(self, req: Request, out: Any = None) -> None:
        resp = self.do(req)
        env: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError):
            env = json.loads(resp.body)
        code = int(env.get("Code", 0) or 0)
        if code not in (0, 1000, 1001):
            raise APIError(
                http_status=resp.status,
                code=code,
                message=str(env.get("Error", "")),
                raw_body=resp.body,
            )
        if out is None:
            return
        if isinstance(out, dict):
            out.clear()
            out.update(json.loads(resp.body))
            return
        parsed = json.loads(resp.body)
        if hasattr(out, "__dataclass_fields__"):
            for k, v in parsed.items():
                snake = _to_snake(k)
                if hasattr(out, snake):
                    setattr(out, snake, v)
        elif isinstance(out, list):
            key = _response_list_key(parsed)
            out.extend(parsed.get(key, []))
        else:
            out._payload = parsed

    def _do_once(self, req: Request) -> Response:
        with self._lock:
            uid, access = self._uid, self._access
        url = self.base_url + req.path
        if req.query:
            url += "?" + urlencode(req.query)
        headers = {
            "User-Agent": self.user_agent,
            "x-pm-appversion": self.app_version,
        }
        content: bytes | str | None = None
        if req.body is not None:
            if isinstance(req.body, (bytes, bytearray)):
                content = bytes(req.body)
            elif isinstance(req.body, str):
                content = req.body
            else:
                content = json.dumps(req.body)
                headers.setdefault("Content-Type", "application/json")
        if req.content_type:
            headers["Content-Type"] = req.content_type
        elif content is not None and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        if uid:
            headers["x-pm-uid"] = uid
        if access:
            headers["Authorization"] = f"Bearer {access}"
        if req.hv_token and req.hv_type:
            headers["x-pm-human-verification-token"] = req.hv_token
            headers["x-pm-human-verification-token-type"] = req.hv_type
        try:
            response = self._client.request(
                req.method.upper(), url, headers=headers, content=content
            )
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        return Response(
            status=response.status_code,
            body=response.content,
            retry_after=response.headers.get("Retry-After", ""),
        )

    def _refresh_auth(self) -> bool:
        with self._lock:
            uid, _, refresh = self._uid, self._access, self._refresh
        if not refresh:
            return False
        body = {"RefreshToken": refresh, "GrantType": "refresh_token"}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "x-pm-appversion": self.app_version,
            "x-pm-uid": uid,
        }
        try:
            resp = self._client.put(
                f"{self.base_url}/auth/v4/refresh",
                headers=headers,
                content=json.dumps(body),
            )
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        data = resp.json()
        if int(data.get("Code", 0)) != 1000:
            return False
        with self._lock:
            self._access = str(data.get("AccessToken", ""))
            if data.get("RefreshToken"):
                self._refresh = str(data["RefreshToken"])
        return True

    def raw_auth(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        hv_token: str = "",
        hv_type: str = "",
        extra_headers: dict[str, str] | None = None,
    ) -> bytes:
        with self._lock:
            uid, access = self._uid, self._access
        url = self.base_url + path
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "x-pm-appversion": self.app_version,
        }
        if uid:
            headers["x-pm-uid"] = uid
        if access:
            headers["Authorization"] = f"Bearer {access}"
        if hv_token and hv_type:
            headers["x-pm-human-verification-token"] = hv_token
            headers["x-pm-human-verification-token-type"] = hv_type
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self._client.request(method.upper(), url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        return resp.content


def _to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _response_list_key(parsed: dict[str, Any]) -> str:
    for key in parsed:
        if key != "Code" and isinstance(parsed[key], list):
            return key
    return "Items"


def _retry_after_seconds(header: str) -> float | None:
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def _classify_error(status: int, body: bytes) -> tuple[HumanVerificationError | None, APIError]:
    try:
        env = json.loads(body)
    except json.JSONDecodeError:
        return None, APIError(http_status=status, raw_body=body)
    code = int(env.get("Code", 0) or 0)
    if code == 9001:
        details = env.get("Details") or {}
        return (
            HumanVerificationError(
                token=str(details.get("HumanVerificationToken", "")),
                methods=list(details.get("HumanVerificationMethods") or []),
                web_url=str(details.get("WebUrl", details.get("WebURL", ""))),
            ),
            APIError(
                http_status=status, code=code, message=str(env.get("Error", "")), raw_body=body
            ),
        )
    return None, APIError(
        http_status=status,
        code=code,
        message=str(env.get("Error", "")),
        raw_body=body,
    )
