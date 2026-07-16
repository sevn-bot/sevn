"""SRP authentication flow for Proton API."""

from __future__ import annotations

import base64
import json

from proton_cli.crypto.modulus import decode_modulus
from proton_cli.crypto.srp.user import User
from proton_cli.proton.client import Client
from proton_cli.proton.errors import HumanVerificationError


def login(client: Client, username: str, password: str, totp: str = "") -> None:
    """Perform full web-client auth: session → SRP → optional 2FA."""
    sess = _create_session(client)
    client.set_tokens(sess["UID"], sess["AccessToken"], sess["RefreshToken"])
    auth = _login_srp(client, username, password, "", "")
    client.set_tokens(auth["UID"], auth["AccessToken"], auth["RefreshToken"])
    if int(auth.get("2FA", {}).get("Enabled", 0) or 0) & 1:
        if not totp:
            raise ValueError("account requires 2FA but no TOTP code provided")
        _auth_2fa(client, totp)


def _create_session(client: Client) -> dict:
    body = b"{}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": client.user_agent,
        "x-pm-appversion": client.app_version,
        "x-enforce-unauthsession": "true",
    }
    resp = client._client.post(f"{client.base_url}/auth/v4/sessions", headers=headers, content=body)
    data = resp.json()
    if int(data.get("Code", 0)) != 1000:
        msg = f"session creation code {data.get('Code')}: {resp.text}"
        raise ValueError(msg)
    return data


def _get_auth_info(client: Client, username: str) -> dict:
    body = json.dumps({"Username": username}).encode()
    raw = client.raw_auth("POST", "/core/v4/auth/info", body)
    data = json.loads(raw)
    if int(data.get("Code", 0)) != 1000:
        msg = f"auth info code {data.get('Code')}: {raw.decode()}"
        raise ValueError(msg)
    return data


def _login_srp(
    client: Client,
    username: str,
    password: str,
    hv_token: str,
    hv_type: str,
) -> dict:
    info = _get_auth_info(client, username)
    return _srp_login(client, username, password, info, hv_token, hv_type)


def _srp_login(
    client: Client,
    username: str,
    password: str,
    info: dict,
    hv_token: str,
    hv_type: str,
) -> dict:
    modulus = decode_modulus(str(info["Modulus"]))
    server_challenge = base64.b64decode(info["ServerEphemeral"])
    salt = base64.b64decode(info["Salt"])
    version = int(info["Version"])

    user = User(password, modulus)
    client_proof = user.process_challenge(salt, server_challenge, version)
    if client_proof is None:
        raise ValueError("SRP challenge failed")

    payload = {
        "Username": username,
        "ClientProof": base64.b64encode(client_proof).decode(),
        "ClientEphemeral": base64.b64encode(user.get_challenge()).decode(),
        "SRPSession": info["SRPSession"],
    }
    raw = client.raw_auth(
        "POST",
        "/core/v4/auth",
        json.dumps(payload).encode(),
        hv_token=hv_token,
        hv_type=hv_type,
    )
    data = json.loads(raw)
    code = int(data.get("Code", 0))
    if code == 9001:
        details = data.get("Details") or {}
        raise HumanVerificationError(
            token=str(details.get("HumanVerificationToken", "")),
            methods=list(details.get("HumanVerificationMethods") or []),
            web_url=str(details.get("WebUrl", "")),
        )
    if code != 1000:
        msg = f"auth code {code}: {raw.decode()}"
        raise ValueError(msg)

    server_proof = base64.b64decode(data["ServerProof"])
    user.verify_session(server_proof)
    if not user.authenticated():
        raise ValueError("server proof verification failed")
    return data


def _auth_2fa(client: Client, totp: str) -> None:
    body = json.dumps({"TwoFactorCode": totp}).encode()
    raw = client.raw_auth("POST", "/core/v4/auth/2fa", body)
    data = json.loads(raw)
    if int(data.get("Code", 0)) != 1000:
        msg = f"2FA code {data.get('Code')}: {raw.decode()}"
        raise ValueError(msg)
