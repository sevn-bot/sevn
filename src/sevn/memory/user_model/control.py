"""Owner controls for inferred profile (`specs/32-memory-honcho.md` §2.6).

Module: sevn.memory.user_model.control
Depends: json, shutil, pathlib, sevn.memory.user_model.deny_topics, sevn.memory.user_model.store

Exports:
    UserModelControl — promote / delete / suppress mutations on disk.

Examples:
    >>> from sevn.memory.user_model.control import UserModelControl
    >>> UserModelControl
    <class 'sevn.memory.user_model.control.UserModelControl'>
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sevn.memory.user_model.deny_topics import topic_denied
from sevn.memory.user_model.store import UserModelStore


class UserModelControl:
    """Promote / delete / suppress — mutates disk under ``workspace_root``."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        store: UserModelStore | None = None,
    ) -> None:
        """Create a control handle rooted at ``workspace_root``.

        Args:
            workspace_root (str | Path): Workspace content root.
            store (UserModelStore | None): Optional store override for tests.

        Returns:
            None: Always.

        Examples:
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from sevn.memory.user_model.control import UserModelControl
            >>> with TemporaryDirectory() as d:
            ...     c = UserModelControl(Path(d).resolve())
            ...     isinstance(c, UserModelControl)
            True
        """

        self._root = Path(workspace_root).expanduser().resolve()
        self._store = store or UserModelStore()
        self._sevn_json = self._root / "sevn.json"

    def promote_to_user_md(self, fact_id: str, *, backup: bool = True) -> None:
        """Append ``value`` to ``USER.md``, remove fact, optional JSON backup.

        Args:
            fact_id (str): Fact id to promote.
            backup (bool): When True, copy ``user_model.json`` before mutation.

        Returns:
            None: Always.

        Raises:
            ValueError: When the fact id is unknown.

        Examples:
            >>> from datetime import UTC, datetime
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from sevn.memory.user_model.control import UserModelControl
            >>> from sevn.memory.user_model.models import InferredFact, UserProfile
            >>> from sevn.memory.user_model.store import UserModelStore
            >>> with TemporaryDirectory() as d:
            ...     root = Path(d).resolve()
            ...     _ = (root / "sevn.json").write_text('{"schema_version": 1}', encoding="utf-8")
            ...     prof = UserProfile(
            ...         workspace_id="w",
            ...         updated_at=datetime.now(tz=UTC),
            ...         facts=[
            ...             InferredFact(
            ...                 id="f1",
            ...                 topic="t",
            ...                 value="note",
            ...                 confidence="high",
            ...                 last_observed_at=datetime.now(tz=UTC),
            ...             ),
            ...         ],
            ...     )
            ...     UserModelStore().save(str(root), prof)
            ...     UserModelControl(root).promote_to_user_md("f1", backup=False)
            ...     (root / "USER.md").read_text(encoding="utf-8").strip()
            'note'
        """

        prof = self._store.load(str(self._root))
        fact = next((f for f in prof.facts if f.id == fact_id), None)
        if fact is None:
            msg = f"unknown fact id {fact_id!r}"
            raise ValueError(msg)
        user_md = self._root / "USER.md"
        line = f"\n{fact.value}\n"
        user_md.parent.mkdir(parents=True, exist_ok=True)
        with user_md.open("a", encoding="utf-8") as fh:
            fh.write(line)
        path = self._root / ".sevn" / "user_model.json"
        if backup and path.is_file():
            shutil.copyfile(path, path.with_suffix(".json.bak-promote"))
        remaining = [f for f in prof.facts if f.id != fact_id]
        self._store.save(str(self._root), prof.model_copy(update={"facts": remaining}))

    def delete_fact(self, fact_id: str, *, backup: bool = True) -> None:
        """Remove one fact by id.

        Args:
            fact_id (str): Fact id to delete.
            backup (bool): When True, copy ``user_model.json`` before mutation.

        Returns:
            None: Always.

        Raises:
            ValueError: When the fact id is unknown.

        Examples:
            >>> from datetime import UTC, datetime
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from sevn.memory.user_model.control import UserModelControl
            >>> from sevn.memory.user_model.models import InferredFact, UserProfile
            >>> from sevn.memory.user_model.store import UserModelStore
            >>> with TemporaryDirectory() as d:
            ...     root = Path(d).resolve()
            ...     _ = (root / "sevn.json").write_text('{"schema_version": 1}', encoding="utf-8")
            ...     prof = UserProfile(
            ...         workspace_id="w",
            ...         updated_at=datetime.now(tz=UTC),
            ...         facts=[
            ...             InferredFact(
            ...                 id="f1",
            ...                 topic="t",
            ...                 value="v",
            ...                 confidence="high",
            ...                 last_observed_at=datetime.now(tz=UTC),
            ...             ),
            ...         ],
            ...     )
            ...     UserModelStore().save(str(root), prof)
            ...     UserModelControl(root).delete_fact("f1", backup=False)
            ...     UserModelStore().load(str(root)).facts == []
            True
        """

        prof = self._store.load(str(self._root))
        if not any(f.id == fact_id for f in prof.facts):
            msg = f"unknown fact id {fact_id!r}"
            raise ValueError(msg)
        path = self._root / ".sevn" / "user_model.json"
        if backup and path.is_file():
            shutil.copyfile(path, path.with_suffix(".json.bak-delete"))
        remaining = [f for f in prof.facts if f.id != fact_id]
        self._store.save(str(self._root), prof.model_copy(update={"facts": remaining}))

    def suppress_topic(self, topic: str) -> None:
        """Append a deny pattern to ``memory.user_model.deny_topics`` in ``sevn.json``.

        Args:
            topic (str): Topic substring or pattern to append to ``deny_topics``.

        Returns:
            None: Always.

        Raises:
            FileNotFoundError: When ``sevn.json`` is missing.

        Examples:
            >>> from datetime import UTC, datetime
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from sevn.memory.user_model.control import UserModelControl
            >>> from sevn.memory.user_model.models import InferredFact, UserProfile
            >>> from sevn.memory.user_model.store import UserModelStore
            >>> with TemporaryDirectory() as d:
            ...     root = Path(d).resolve()
            ...     _ = (root / "sevn.json").write_text('{"schema_version": 1}', encoding="utf-8")
            ...     prof = UserProfile(
            ...         workspace_id="w",
            ...         updated_at=datetime.now(tz=UTC),
            ...         facts=[
            ...             InferredFact(
            ...                 id="f1",
            ...                 topic="bad",
            ...                 value="v",
            ...                 confidence="high",
            ...                 last_observed_at=datetime.now(tz=UTC),
            ...             ),
            ...         ],
            ...     )
            ...     UserModelStore().save(str(root), prof)
            ...     UserModelControl(root).suppress_topic("bad")
            ...     UserModelStore().load(str(root)).facts == []
            True
        """

        if not self._sevn_json.is_file():
            msg = f"missing sevn.json at {self._sevn_json}"
            raise FileNotFoundError(msg)
        data = json.loads(self._sevn_json.read_text(encoding="utf-8"))
        mem = data.setdefault("memory", {})
        um = mem.setdefault("user_model", {})
        dt = list(um.get("deny_topics") or [])
        if topic not in dt:
            dt.append(topic)
        um["deny_topics"] = dt
        tmp = self._sevn_json.with_suffix(".json.tmp-user-model")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._sevn_json)
        prof = self._store.load(str(self._root))
        deny = list(um.get("deny_topics") or [])
        kept = [f for f in prof.facts if not topic_denied(f.topic, deny)]
        self._store.save(str(self._root), prof.model_copy(update={"facts": kept}))


__all__ = ["UserModelControl"]
