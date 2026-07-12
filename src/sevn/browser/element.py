"""Element location + interaction via synthetic CDP input events.

:class:`Dom` finds elements by CSS selector, visible text, or accessibility role over
one page :class:`~sevn.browser.cdp.session.CDPSession`. :class:`ElementHandle` performs
human-like interactions: clicks dispatched as real ``Input`` mouse gestures at the
element's box-model centre (with a JS-click fallback), typing via ``Input.insertText``,
clearing+filling, option selection, hover, and focus.

Module: sevn.browser.element
Depends: asyncio, contextlib, sevn.browser.cdp

Exports:
    Dom — selector/text/role element finders over a page session.
    ElementHandle — synthetic click/type/fill/select on one resolved node.
    ElementError — raised when a node cannot be resolved or located.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(ElementHandle.click)
    True
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.cdp import CDPError

if TYPE_CHECKING:
    from sevn.browser.cdp import CDPSession

# Visible-text best-match finder; __NEEDLE__ is a JS string literal, __BEST__ a bool token.
_FIND_BY_TEXT_JS: Final[str] = (
    "(() => { const needle = __NEEDLE__; const nodes = Array.from("
    "document.querySelectorAll('a,button,input,[role],label,span,div,li,td,th,p,h1,h2,h3'));"
    " let best = null; let bestLen = Infinity;"
    " for (const el of nodes) {"
    "  const t = (el.innerText || el.value || el.getAttribute('aria-label') || '')"
    ".trim().toLowerCase();"
    "  if (t && t.includes(needle)) {"
    "   if (!__BEST__) { return el; }"
    "   if (t.length < bestLen) { best = el; bestLen = t.length; } } }"
    " return best; })()"
)
# Accessibility role finder; __ROLE__ and __NAME__ are JS string literals.
_FIND_BY_ROLE_JS: Final[str] = (
    "(() => { const role = __ROLE__; const name = __NAME__;"
    " const sel = `[role='${role}']`;"
    " const nodes = Array.from(document.querySelectorAll(sel));"
    " for (const el of nodes) {"
    "  const n = (el.getAttribute('aria-label') || el.innerText || '')"
    ".trim().toLowerCase();"
    "  if (!name || n.includes(name)) { return el; } }"
    " return null; })()"
)

_KEY_CODES: Final[dict[str, dict[str, Any]]] = {
    "Enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    "Tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
    "Backspace": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
    "Escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
    "ArrowDown": {"key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
    "ArrowUp": {"key": "ArrowUp", "code": "ArrowUp", "windowsVirtualKeyCode": 38},
}


class ElementError(RuntimeError):
    """An element could not be resolved or located."""


def _quad_center(quad: list[float]) -> tuple[float, float]:
    """Return the centre point of a box-model quad.

    Args:
        quad (list[float]): Eight numbers ``[x1,y1,x2,y2,x3,y3,x4,y4]``.

    Returns:
        tuple[float, float]: ``(x, y)`` centre.

    Examples:
        >>> _quad_center([0, 0, 10, 0, 10, 10, 0, 10])
        (5.0, 5.0)
    """
    xs = quad[0::2]
    ys = quad[1::2]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


class ElementHandle:
    """A resolved page node with synthetic-input interaction methods."""

    def __init__(
        self,
        session: CDPSession,
        *,
        node_id: int | None = None,
        object_id: str | None = None,
    ) -> None:
        """Bind a session and node identity (``nodeId`` and/or Runtime ``objectId``).

        Args:
            session (CDPSession): Page session that owns the node.
            node_id (int | None): CDP DOM ``nodeId`` when known.
            object_id (str | None): Runtime remote ``objectId`` when known.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ElementHandle.__init__)
            True
        """
        self._session = session
        self._node_id = node_id
        self._object_id = object_id

    async def _resolve_node_id(self) -> int:
        """Return the DOM ``nodeId``, resolving from an ``objectId`` when needed.

        Returns:
            int: CDP DOM node id.

        Raises:
            ElementError: When no node identity is available.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle._resolve_node_id)
            True
        """
        if self._node_id is not None:
            return self._node_id
        if self._object_id is not None:
            result = await self._session.send("DOM.requestNode", {"objectId": self._object_id})
            node_id = result.get("nodeId")
            if isinstance(node_id, int):
                self._node_id = node_id
                return node_id
        msg = "element has no resolvable nodeId"
        raise ElementError(msg)

    async def _resolve_object_id(self) -> str:
        """Return a Runtime ``objectId``, resolving from a ``nodeId`` when needed.

        Returns:
            str: Runtime remote object id.

        Raises:
            ElementError: When no object identity is available.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle._resolve_object_id)
            True
        """
        if self._object_id is not None:
            return self._object_id
        if self._node_id is not None:
            result = await self._session.send("DOM.resolveNode", {"nodeId": self._node_id})
            obj = (result.get("object") or {}).get("objectId")
            if isinstance(obj, str):
                self._object_id = obj
                return obj
        msg = "element has no resolvable objectId"
        raise ElementError(msg)

    async def _call_js(self, function_declaration: str, *args: Any) -> Any:
        """Call a JS function with ``this`` bound to the element.

        Args:
            function_declaration (str): ``function(...) { ... }`` source.
            args (Any): JSON-serialisable arguments passed by value.

        Returns:
            Any: The returned JSON value.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle._call_js)
            True
        """
        object_id = await self._resolve_object_id()
        result = await self._session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": function_declaration,
                "arguments": [{"value": a} for a in args],
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        return (result.get("result") or {}).get("value")

    async def scroll_into_view(self) -> None:
        """Scroll the element into the viewport if needed (best effort).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.scroll_into_view)
            True
        """
        node_id = await self._resolve_node_id()
        with contextlib.suppress(CDPError):
            await self._session.send("DOM.scrollIntoViewIfNeeded", {"nodeId": node_id})

    async def center(self) -> tuple[float, float]:
        """Return the element's box-model centre point.

        Returns:
            tuple[float, float]: ``(x, y)`` viewport coordinates.

        Raises:
            ElementError: When the box model is unavailable (hidden/zero-size).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.center)
            True
        """
        node_id = await self._resolve_node_id()
        try:
            result = await self._session.send("DOM.getBoxModel", {"nodeId": node_id})
        except CDPError as exc:
            raise ElementError(f"no box model: {exc}") from exc
        quad = (result.get("model") or {}).get("content")
        if not isinstance(quad, list) or len(quad) < 8:
            msg = "element has no content quad"
            raise ElementError(msg)
        return _quad_center([float(n) for n in quad[:8]])

    async def focus(self) -> None:
        """Focus the element (``DOM.focus``).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.focus)
            True
        """
        node_id = await self._resolve_node_id()
        with contextlib.suppress(CDPError):
            await self._session.send("DOM.focus", {"nodeId": node_id})

    async def click(self) -> None:
        """Click via a synthetic mouse gesture at the element centre (D6).

        Scrolls into view, then dispatches ``mouseMoved`` → ``mousePressed`` →
        ``mouseReleased``. Falls back to a JS ``.click()`` when no box model exists
        (off-screen/occluded).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.click)
            True
        """
        await self.scroll_into_view()
        try:
            x, y = await self.center()
        except ElementError:
            await self._call_js("function() { this.click(); }")
            return
        await self._session.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for event in ("mousePressed", "mouseReleased"):
            await self._session.send(
                "Input.dispatchMouseEvent",
                {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    async def hover(self) -> None:
        """Hover the element by moving the synthetic mouse to its centre.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.hover)
            True
        """
        await self.scroll_into_view()
        x, y = await self.center()
        await self._session.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    async def type(self, text: str) -> None:
        """Focus then insert ``text`` as a paste-like input event.

        Args:
            text (str): Text to insert at the caret.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.type)
            True
        """
        await self.focus()
        await self._session.send("Input.insertText", {"text": text})

    async def fill(self, value: str) -> None:
        """Clear the field then type ``value`` (focus + JS clear + insertText).

        Args:
            value (str): Replacement value.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.fill)
            True
        """
        await self.focus()
        await self._call_js(
            "function() { if ('value' in this) { this.value = ''; "
            "this.dispatchEvent(new Event('input', {bubbles: true})); } }"
        )
        await self._session.send("Input.insertText", {"text": value})
        await self._call_js(
            "function() { this.dispatchEvent(new Event('input', {bubbles: true})); "
            "this.dispatchEvent(new Event('change', {bubbles: true})); }"
        )

    async def select_option(self, value: str) -> None:
        """Select a ``<select>`` option by value and fire ``change``.

        Args:
            value (str): Option value to select.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.select_option)
            True
        """
        await self._call_js(
            "function(v) { this.value = v; "
            "this.dispatchEvent(new Event('change', {bubbles: true})); }",
            value,
        )

    async def press_key(self, key: str) -> None:
        """Dispatch a single named key (``Enter``, ``Tab``, ``Backspace``, ...).

        Args:
            key (str): Key name from the supported key table.

        Returns:
            None

        Raises:
            ElementError: When the key name is unknown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.press_key)
            True
        """
        spec = _KEY_CODES.get(key)
        if spec is None:
            msg = f"unsupported key: {key!r}"
            raise ElementError(msg)
        await self.focus()
        await self._session.send("Input.dispatchKeyEvent", {"type": "keyDown", **spec})
        await self._session.send("Input.dispatchKeyEvent", {"type": "keyUp", **spec})

    async def text(self) -> str:
        """Return the element's ``innerText``.

        Returns:
            str: Visible text content.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ElementHandle.text)
            True
        """
        return str(await self._call_js("function() { return this.innerText || ''; }") or "")


class Dom:
    """Element finders (selector / text / role) over one page session."""

    def __init__(self, session: CDPSession) -> None:
        """Bind a page CDP session.

        Args:
            session (CDPSession): Session bound to a page target.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Dom.__init__)
            True
        """
        self._session = session

    async def _root_node_id(self) -> int:
        """Return the document root ``nodeId`` (``DOM.getDocument``).

        Returns:
            int: Root node id.

        Raises:
            ElementError: When the document root is unavailable.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Dom._root_node_id)
            True
        """
        with contextlib.suppress(CDPError):
            await self._session.enable("DOM")
        result = await self._session.send("DOM.getDocument", {"depth": 0})
        node_id = (result.get("root") or {}).get("nodeId")
        if not isinstance(node_id, int):
            msg = "no document root nodeId"
            raise ElementError(msg)
        return node_id

    async def query(self, selector: str) -> ElementHandle | None:
        """Return the first element matching a CSS ``selector``, or ``None``.

        Args:
            selector (str): CSS selector.

        Returns:
            ElementHandle | None: Handle for the matched node or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Dom.query)
            True
        """
        root = await self._root_node_id()
        result = await self._session.send(
            "DOM.querySelector", {"nodeId": root, "selector": selector}
        )
        node_id = result.get("nodeId")
        if isinstance(node_id, int) and node_id:
            return ElementHandle(self._session, node_id=node_id)
        return None

    async def query_all(self, selector: str) -> list[ElementHandle]:
        """Return all elements matching a CSS ``selector``.

        Args:
            selector (str): CSS selector.

        Returns:
            list[ElementHandle]: Handles for matched nodes.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Dom.query_all)
            True
        """
        root = await self._root_node_id()
        result = await self._session.send(
            "DOM.querySelectorAll", {"nodeId": root, "selector": selector}
        )
        node_ids = result.get("nodeIds")
        if not isinstance(node_ids, list):
            return []
        return [ElementHandle(self._session, node_id=n) for n in node_ids if isinstance(n, int)]

    async def find_by_text(self, text: str, *, best_match: bool = True) -> ElementHandle | None:
        """Return the best element whose visible text contains ``text``.

        Args:
            text (str): Text to search for (case-insensitive, trimmed).
            best_match (bool): Prefer the smallest/most-specific match when ``True``.

        Returns:
            ElementHandle | None: Handle for the matched node or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Dom.find_by_text)
            True
        """
        with contextlib.suppress(CDPError):
            await self._session.enable("Runtime")
        needle = json.dumps(text.strip().lower())
        script = _FIND_BY_TEXT_JS.replace("__NEEDLE__", needle).replace(
            "__BEST__", "true" if best_match else "false"
        )
        result = await self._session.send(
            "Runtime.evaluate", {"expression": script, "returnByValue": False}
        )
        object_id = (result.get("result") or {}).get("objectId")
        if isinstance(object_id, str) and object_id:
            return ElementHandle(self._session, object_id=object_id)
        return None

    async def find_by_role(self, role: str, name: str = "") -> ElementHandle | None:
        """Return an element by accessibility ``role`` and optional accessible ``name``.

        Args:
            role (str): ARIA/computed role (for example ``button``).
            name (str): Accessible name substring to require (case-insensitive).

        Returns:
            ElementHandle | None: Handle for the matched node or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Dom.find_by_role)
            True
        """
        with contextlib.suppress(CDPError):
            await self._session.enable("Runtime")
        script = _FIND_BY_ROLE_JS.replace("__ROLE__", json.dumps(role)).replace(
            "__NAME__", json.dumps(name.strip().lower())
        )
        result = await self._session.send(
            "Runtime.evaluate", {"expression": script, "returnByValue": False}
        )
        object_id = (result.get("result") or {}).get("objectId")
        if isinstance(object_id, str) and object_id:
            return ElementHandle(self._session, object_id=object_id)
        return None


__all__ = ["Dom", "ElementError", "ElementHandle"]
