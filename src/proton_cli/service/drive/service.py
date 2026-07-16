"""Proton Drive operations."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO

import httpx
from pgpy import PGPKey, PGPMessage

from proton_cli.account.keys import use_unlocked_key
from proton_cli.errors import NotFound
from proton_cli.proton.client import Client, Request
from proton_cli.service.drive import blocks, crypto, paths

if TYPE_CHECKING:
    from proton_cli.account.keys import Unlocked

BLOCK_SIZE = 4 * 1024 * 1024


@dataclass
class Child:
    link_id: str
    name: str
    type: int
    size: int = 0
    create_time: int = 0
    modify_time: int = 0
    path: str = ""


@dataclass
class TrashEntry:
    share_id: str
    link_id: str
    type: int = 0
    size: int = 0


@dataclass
class UploadOptions:
    mime_type: str = "application/octet-stream"


class DriveService:
    def __init__(self, client: Client) -> None:
        self._client = client

    def resolve(self, unlocked: Unlocked) -> crypto.DriveContext:
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/drive/volumes"), payload)
        volumes = payload.get("Volumes") or []
        if not volumes:
            raise ValueError("no volumes found")
        vol = volumes[0]
        share = vol.get("Share") or {}
        return self._unlock_share(
            unlocked,
            str(share.get("ShareID", "")),
            str(share.get("LinkID", "")),
            str(vol.get("VolumeID", "")),
        )

    def _unlock_share(
        self,
        unlocked: Unlocked,
        share_id: str,
        root_link_id: str,
        volume_id: str,
    ) -> crypto.DriveContext:
        share_payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/drive/shares/{share_id}"),
            share_payload,
        )
        share_key, addr_id, addr_email = crypto.unlock_share(
            unlocked.addr_keys,
            unlocked.addresses,
            share_payload,
        )
        addr_keys = unlocked.addr_keys.get(addr_id)
        if not addr_keys:
            raise ValueError(f"no key ring for address {addr_id}")
        return crypto.DriveContext(
            share_id=share_id,
            volume_id=volume_id,
            root_link_id=root_link_id,
            addr_id=addr_id,
            addr_email=addr_email,
            share_key=share_key,
            addr_key=addr_keys[0],
        )

    def list_children(self, dc: crypto.DriveContext, path: str = "/") -> list[Child]:
        resolved = self.resolve_path(dc, path)
        if not resolved.is_folder:
            raise ValueError(f"{path} is not a folder")
        raw = self._list_raw_children(resolved.share_id, resolved.link_id)
        out: list[Child] = []
        for item in raw:
            try:
                name = crypto.decrypt_name(item.name, resolved.node_key)
            except Exception:
                name = "(decrypt failed)"
            out.append(
                Child(
                    link_id=item.link_id,
                    name=name,
                    type=item.type,
                    size=item.size,
                    create_time=item.create_time,
                    modify_time=item.modify_time,
                )
            )
        return out

    def resolve_path(self, dc: crypto.DriveContext, path: str) -> crypto.Resolved:
        path = paths.normalize_path(path)
        root = self._get_link(dc.share_id, dc.root_link_id)
        root_key = crypto.unlock_node(root, dc.share_key, dc.addr_key)
        if path == "/":
            return crypto.Resolved(
                share_id=dc.share_id,
                link_id=dc.root_link_id,
                parent_key=dc.share_key,
                node_key=root_key,
                name="",
                is_folder=True,
            )
        parts = [p for p in path.strip("/").split("/") if p]
        current_id = dc.root_link_id
        current_key = root_key
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            children = self._list_raw_children(dc.share_id, current_id)
            found: crypto.Link | None = None
            for ch in children:
                try:
                    name = crypto.decrypt_name(ch.name, current_key)
                except Exception:
                    continue
                if name == part:
                    found = ch
                    break
            if found is None:
                raise NotFound("path", part)
            child_key = crypto.unlock_node(found, current_key, dc.addr_key)
            if is_last:
                return crypto.Resolved(
                    share_id=dc.share_id,
                    link_id=found.link_id,
                    parent_key=current_key,
                    node_key=child_key,
                    name=part,
                    is_folder=found.type == 1,
                )
            if found.type != 1:
                raise ValueError(f"{part} is not a folder")
            current_key = child_key
            current_id = found.link_id
        raise ValueError("path resolution failed")

    def create_folder(self, dc: crypto.DriveContext, full_path: str) -> None:
        full_path = paths.normalize_path(full_path)
        parent_path = paths.dir_of(full_path)
        name = paths.base_of(full_path)
        parent = self.resolve_path(dc, parent_path)
        parent_link = self._get_link(parent.share_id, parent.link_id)
        hash_key = crypto.hash_key_of(parent_link, parent.node_key)
        digest = crypto.lookup_hash(name.lower(), hash_key)
        enc_name = crypto.encrypt_name(name, parent.node_key, dc.addr_key)
        node_key_arm, node_pass, node_pass_sig, node_priv, _phrase = crypto.gen_node_keys(
            parent.node_key, dc.addr_key
        )
        hash_key_enc = crypto.gen_node_hash_key(node_priv)
        body = {
            "Name": enc_name,
            "Hash": digest,
            "ParentLinkID": parent.link_id,
            "NodePassphrase": node_pass,
            "NodePassphraseSignature": node_pass_sig,
            "SignatureAddress": dc.addr_email,
            "NodeKey": node_key_arm,
            "NodeHashKey": hash_key_enc,
        }
        self._client.decode(
            Request(method="POST", path=f"/drive/shares/{parent.share_id}/folders", body=body),
        )

    def upload(
        self,
        dc: crypto.DriveContext,
        dest_path: str,
        name: str,
        reader: BinaryIO,
        opts: UploadOptions | None = None,
    ) -> None:
        opts = opts or UploadOptions()
        parent = self.resolve_path(dc, paths.normalize_path(dest_path))
        if not parent.is_folder:
            raise ValueError(f"{dest_path} is not a folder")
        parent_link = self._get_link(parent.share_id, parent.link_id)
        hash_key = crypto.hash_key_of(parent_link, parent.node_key)
        digest = crypto.lookup_hash(name.lower(), hash_key)
        enc_name = crypto.encrypt_name(name, parent.node_key, dc.addr_key)
        node_key_arm, node_pass, node_pass_sig, node_priv, _phrase = crypto.gen_node_keys(
            parent.node_key, dc.addr_key
        )
        sk = blocks.make_session_key()
        content_kp = blocks.encrypt_session_key_packet(node_priv, sk)
        content_sig = blocks.sign_session_key(node_priv, sk)

        create_payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path=f"/drive/shares/{parent.share_id}/files",
                body={
                    "Name": enc_name,
                    "Hash": digest,
                    "ParentLinkID": parent.link_id,
                    "NodePassphrase": node_pass,
                    "NodePassphraseSignature": node_pass_sig,
                    "SignatureAddress": dc.addr_email,
                    "NodeKey": node_key_arm,
                    "MIMEType": opts.mime_type,
                    "ContentKeyPacket": base64.b64encode(content_kp).decode(),
                    "ContentKeyPacketSignature": content_sig,
                },
            ),
            create_payload,
        )
        file_obj = create_payload.get("File") or {}
        link_id = str(file_obj.get("ID", ""))
        revision_id = str(file_obj.get("RevisionID", ""))
        if not link_id or not revision_id:
            raise ValueError("file creation did not return ids")

        ver_payload: dict = {}
        self._client.decode(
            Request(
                method="GET",
                path=f"/drive/shares/{parent.share_id}/links/{link_id}/revisions/{revision_id}/verification",
            ),
            ver_payload,
        )
        ver_code = base64.b64decode(str(ver_payload.get("VerificationCode", "")))

        block_infos: list[dict[str, object]] = []
        index = 0
        while True:
            chunk = reader.read(BLOCK_SIZE)
            if not chunk:
                break
            index += 1
            enc_data, enc_sig = blocks.encrypt_block(chunk, sk, node_priv, dc.addr_key)
            digest_bytes = hashlib.sha256(enc_data).digest()
            verifier = bytearray(len(ver_code))
            for j, b in enumerate(ver_code):
                verifier[j] = b ^ (enc_data[j] if j < len(enc_data) else 0)
            block_infos.append(
                {
                    "index": index,
                    "hash": base64.b64encode(digest_bytes).decode(),
                    "enc_sig": enc_sig,
                    "size": len(enc_data),
                    "enc_data": enc_data,
                    "verifier": base64.b64encode(bytes(verifier)).decode(),
                }
            )

        block_list = [
            {
                "Hash": b["hash"],
                "EncSignature": b["enc_sig"],
                "Size": b["size"],
                "Index": b["index"],
                "Verifier": {"Token": b["verifier"]},
            }
            for b in block_infos
        ]
        upload_payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path="/drive/blocks",
                body={
                    "AddressID": dc.addr_id,
                    "ShareID": parent.share_id,
                    "LinkID": link_id,
                    "RevisionID": revision_id,
                    "BlockList": block_list,
                },
            ),
            upload_payload,
        )
        upload_links = upload_payload.get("UploadLinks") or []
        for i, link in enumerate(upload_links):
            self._upload_block(
                link.get("BareURL", ""), link.get("Token", ""), block_infos[i]["enc_data"]
            )

        manifest = b"".join(base64.b64decode(str(b["hash"])) for b in block_infos)
        with use_unlocked_key(dc.addr_key):
            manifest_sig = str(dc.addr_key.sign(PGPMessage.new(manifest)))
        tokens = [
            {"Index": block_infos[i]["index"], "Token": upload_links[i].get("Token", "")}
            for i in range(len(upload_links))
        ]
        self._client.decode(
            Request(
                method="PUT",
                path=f"/drive/shares/{parent.share_id}/files/{link_id}/revisions/{revision_id}",
                body={
                    "BlockList": tokens,
                    "State": 1,
                    "ManifestSignature": manifest_sig,
                    "SignatureAddress": dc.addr_email,
                },
            ),
        )

    def download(self, dc: crypto.DriveContext, path: str, writer: BinaryIO) -> None:
        resolved = self.resolve_path(dc, paths.normalize_path(path))
        if resolved.is_folder:
            raise ValueError(f"{path} is a folder, not a file")
        link = self._get_link(resolved.share_id, resolved.link_id)
        self._download_file(resolved.share_id, link, resolved.node_key, writer)

    def delete(self, dc: crypto.DriveContext, path: str, *, permanent: bool = False) -> None:
        resolved = self.resolve_path(dc, paths.normalize_path(path))
        self._client.decode(
            Request(
                method="POST",
                path=f"/drive/v2/volumes/{dc.volume_id}/trash_multiple",
                body={"LinkIDs": [resolved.link_id]},
            ),
        )
        if permanent:
            self._client.decode(
                Request(
                    method="POST",
                    path=f"/drive/v2/volumes/{dc.volume_id}/trash/delete_multiple",
                    body={"LinkIDs": [resolved.link_id]},
                ),
            )

    def trash_list(self, dc: crypto.DriveContext) -> list[TrashEntry]:
        payload: dict = {}
        self._client.decode(
            Request(
                method="GET",
                path=f"/drive/volumes/{dc.volume_id}/trash",
                query={"Page": "0", "PageSize": "150"},
            ),
            payload,
        )
        out: list[TrashEntry] = []
        for group in payload.get("Trash") or []:
            share_id = str(group.get("ShareID", ""))
            for link_id in group.get("LinkIDs") or []:
                try:
                    link = self._get_link(share_id, str(link_id))
                    out.append(
                        TrashEntry(
                            share_id=share_id,
                            link_id=str(link_id),
                            type=link.type,
                            size=link.size,
                        )
                    )
                except Exception:
                    out.append(TrashEntry(share_id=share_id, link_id=str(link_id)))
        return out

    def trash_restore(self, dc: crypto.DriveContext, link_ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path=f"/drive/v2/volumes/{dc.volume_id}/trash/restore_multiple",
                body={"LinkIDs": link_ids},
            ),
        )

    def trash_empty(self, dc: crypto.DriveContext) -> None:
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/drive/volumes"), payload)
        seen: set[str] = set()
        for vol in payload.get("Volumes") or []:
            vid = str(vol.get("VolumeID", ""))
            if vid and vid not in seen:
                seen.add(vid)
                self._client.decode(
                    Request(method="DELETE", path=f"/drive/volumes/{vid}/trash"),
                )
        if dc.volume_id not in seen:
            self._client.decode(
                Request(method="DELETE", path=f"/drive/volumes/{dc.volume_id}/trash"),
            )

    def _get_link(self, share_id: str, link_id: str) -> crypto.Link:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/drive/shares/{share_id}/links/{link_id}"),
            payload,
        )
        return crypto.link_from_api(payload.get("Link") or {})

    def _list_raw_children(self, share_id: str, link_id: str) -> list[crypto.Link]:
        out: list[crypto.Link] = []
        for page in range(100):
            payload: dict = {}
            self._client.decode(
                Request(
                    method="GET",
                    path=f"/drive/shares/{share_id}/folders/{link_id}/children",
                    query={"Page": str(page), "PageSize": "150"},
                ),
                payload,
            )
            links = payload.get("Links") or []
            if not links:
                break
            out.extend(crypto.link_from_api(raw) for raw in links)
            if len(links) < 150:
                break
        return out

    def _download_file(
        self,
        share_id: str,
        link: crypto.Link,
        node_key: PGPKey,
        writer: BinaryIO,
    ) -> None:
        if not link.file_properties:
            raise ValueError(f"{link.link_id}: no file properties")
        kp = base64.b64decode(str(link.file_properties.get("ContentKeyPacket", "")))
        sk = blocks.decrypt_session_key_packet(kp, node_key)
        revision_id = str((link.file_properties.get("ActiveRevision") or {}).get("ID", ""))
        if not revision_id:
            raise ValueError("file has no active revision")
        rev_payload: dict = {}
        self._client.decode(
            Request(
                method="GET",
                path=f"/drive/shares/{share_id}/files/{link.link_id}/revisions/{revision_id}",
                query={"FromBlockIndex": "1", "PageSize": "50"},
            ),
            rev_payload,
        )
        rev_blocks = (rev_payload.get("Revision") or {}).get("Blocks") or []
        for block in rev_blocks:
            data = self._download_block(block.get("BareURL", ""), block.get("Token", ""))
            plain = blocks.decrypt_block(data, sk)
            writer.write(plain)

    def _download_block(self, url: str, token: str) -> bytes:
        if not url:
            raise ValueError("missing block download url")
        resp = httpx.get(url, headers={"pm-storage-token": token}, timeout=300.0)
        resp.raise_for_status()
        return resp.content

    def _upload_block(self, url: str, token: str, data: bytes) -> None:
        boundary = "proton-cli-boundary"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="Block"; filename="blob"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        resp = httpx.post(
            url,
            content=body,
            headers={
                "pm-storage-token": token,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            timeout=300.0,
        )
        if resp.status_code >= 400:
            raise ValueError(f"upload block failed: HTTP {resp.status_code}: {resp.text}")
