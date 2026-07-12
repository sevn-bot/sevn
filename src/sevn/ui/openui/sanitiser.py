"""HTML allowlist sanitiser (`specs/29-openui.md` §8.1, PRD 10 §5.4).

Module: sevn.ui.openui.sanitiser
Depends: html.parser, re, urllib.parse

Exports:
    sanitise — pure function ``html -> SanitiseResult``.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from sevn.ui.openui.models import Drop, SanitiseResult

_ALLOWED_TAGS = frozenset(
    {
        "div",
        "span",
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "br",
        "b",
        "i",
        "u",
        "strong",
        "em",
        "code",
        "pre",
        "blockquote",
        "a",
        "img",
        "form",
        "input",
        "textarea",
        "select",
        "option",
        "button",
        "label",
        "fieldset",
        "legend",
    },
)

_GLOBAL_BANNED = frozenset(
    {
        "script",
        "iframe",
        "object",
        "embed",
        "link",
        "meta",
        "base",
        "applet",
        "noscript",
        "style",
        "svg",
        "math",
    },
)

_MEDIA_SRC_RE = re.compile(r"^/media/[A-Za-z0-9._~-]+$")

_STYLE_PROP_ALLOW = (
    "color",
    "background-color",
    "font-size",
    "font-weight",
    "font-family",
    "font-style",
    "text-align",
    "text-decoration",
    "text-indent",
    "margin",
    "margin-top",
    "margin-right",
    "margin-bottom",
    "margin-left",
    "padding",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "border",
    "border-top",
    "border-right",
    "border-bottom",
    "border-left",
    "border-width",
    "border-style",
    "border-color",
    "border-radius",
    "width",
    "height",
    "display",
    "flex",
    "flex-direction",
    "flex-wrap",
    "flex-grow",
    "flex-shrink",
    "flex-basis",
    "grid",
    "grid-template-columns",
    "grid-template-rows",
    "grid-column",
    "grid-row",
    "gap",
    "align-items",
    "align-content",
    "align-self",
    "justify-content",
    "justify-items",
    "justify-self",
)


def _allowed_href(href: str) -> bool:
    """Return ``True`` when ``href`` uses an allowed scheme and shape.

    Args:
        href (str): Raw ``href`` attribute value.

    Returns:
        bool: Whether the URL may be kept on ``<a>`` tags.

    Examples:
        >>> _allowed_href("https://example.com")
        True
        >>> _allowed_href("javascript:alert(1)")
        False
    """

    h = href.strip()
    low = h.lower()
    if low.startswith(("javascript:", "vbscript:")):
        return False
    if low.startswith("data:text/html"):
        return False
    parsed = urlparse(h)
    scheme = (parsed.scheme or "").lower()
    return scheme in ("https", "mailto", "tel", "data")


def _allowed_img_src(src: str) -> bool:
    """Return ``True`` for ``data:image/*`` blobs or ``/media/<token>`` paths.

    Args:
        src (str): Raw ``src`` attribute value.

    Returns:
        bool: Whether the image reference is allowlisted.

    Examples:
        >>> _allowed_img_src("/media/abc123")
        True
        >>> _allowed_img_src("file:///etc/passwd")
        False
    """

    s = src.strip()
    if s.lower().startswith("data:image/"):
        return True
    return bool(_MEDIA_SRC_RE.match(s))


def _sanitize_style_value(val: str) -> str | None:
    """Strip ``url()``, ``expression``, ``@import``; keep simple declarations.

    Args:
        val (str): Raw ``style`` attribute string.

    Returns:
        str | None: Sanitised ``;``-joined declarations, or ``None`` when nothing remains.

    Examples:
        >>> _sanitize_style_value("color: red; url(http://x)") is not None
        True
        >>> _sanitize_style_value("background: url(http://x)") is None
        True
    """

    parts_out: list[str] = []
    for chunk in val.split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        low = piece.lower()
        if "url(" in low or "expression(" in low or "@import" in low:
            continue
        if ":" not in piece:
            continue
        prop, _, rest = piece.partition(":")
        prop_key = prop.strip().lower()
        rest_val = rest.strip()
        if any(prop_key == p or prop_key.startswith(p + "-") for p in _STYLE_PROP_ALLOW):
            parts_out.append(f"{prop.strip()}: {rest_val}")
    if not parts_out:
        return None
    return "; ".join(parts_out)


def _filter_attrs(
    tag: str, attrs: list[tuple[str, str | None]]
) -> tuple[str, dict[str, str], list[Drop]]:
    """Allowlist attributes for ``tag`` and collect structured drops.

    Args:
        tag (str): Lowercased tag name.
        attrs (list[tuple[str, str | None]]): Parser attribute tuples.

    Returns:
        tuple[str, dict[str, str], list[Drop]]: Tag name, kept attrs, and drops.

    Examples:
        >>> tag, kept, drops = _filter_attrs("a", [("href", "https://x"), ("onclick", "1")])
        >>> "href" in kept and any(d.attr == "onclick" for d in drops)
        True
    """

    out: dict[str, str] = {}
    drops: list[Drop] = []
    # normalise attrs to dict (last wins)
    raw: dict[str, str] = {}
    for k, v in attrs:
        key = k.lower()
        if key.startswith("on"):
            drops.append(Drop(tag=tag, attr=key, reason="event_handler"))
            continue
        raw[key] = "" if v is None else v

    if tag == "a":
        href = raw.get("href", "")
        if href and not _allowed_href(href):
            drops.append(Drop(tag=tag, attr="href", reason="disallowed_scheme"))
        else:
            if href:
                out["href"] = href
        if raw.get("target", "").lower() == "_blank":
            out["target"] = "_blank"
        out["rel"] = "noopener noreferrer"
        return tag, out, drops

    if tag == "img":
        src = raw.get("src", "")
        if not src or not _allowed_img_src(src):
            drops.append(Drop(tag=tag, attr="src", reason="disallowed_src"))
        else:
            out["src"] = src
        for opt in ("alt", "width", "height"):
            if raw.get(opt):
                out[opt] = raw[opt]
        return tag, out, drops

    if tag == "form":
        action = raw.get("action", "/openui/callback")
        method = raw.get("method", "post").lower()
        if method != "post":
            drops.append(Drop(tag=tag, attr="method", reason="only_post"))
        out["action"] = action
        out["method"] = "post"
        enc = raw.get("enctype", "application/x-www-form-urlencoded")
        if enc in ("application/x-www-form-urlencoded", "multipart/form-data"):
            out["enctype"] = enc
        return tag, out, drops

    if tag == "input":
        t = raw.get("type", "text").lower()
        allowed_types = {
            "text",
            "number",
            "email",
            "url",
            "tel",
            "password",
            "checkbox",
            "radio",
            "hidden",
            "submit",
            "date",
            "time",
        }
        if t not in allowed_types:
            drops.append(Drop(tag=tag, attr="type", reason="input_type"))
            t = "text"
        out["type"] = t
        for k in (
            "name",
            "value",
            "id",
            "class",
            "placeholder",
            "checked",
            "disabled",
            "min",
            "max",
            "step",
        ):
            if k in raw:
                out[k] = raw[k]
        return tag, out, drops

    if tag in {"textarea", "select", "option", "button", "label", "fieldset", "legend"}:
        passthrough = (
            "name",
            "value",
            "id",
            "class",
            "rows",
            "cols",
            "disabled",
            "selected",
            "for",
            "type",
        )
        for k in passthrough:
            if k in raw:
                out[k] = raw[k]
        return tag, out, drops

    if tag == "table":
        for k in ("class", "id", "border", "cellpadding", "cellspacing"):
            if k in raw:
                out[k] = raw[k]
        return tag, out, drops

    # structural + text styling
    passthrough2 = ("class", "id", "colspan", "rowspan", "scope", "headers")
    for k in passthrough2:
        if k in raw:
            out[k] = raw[k]
    if "style" in raw:
        cleaned = _sanitize_style_value(raw["style"])
        if cleaned:
            out["style"] = cleaned
        else:
            drops.append(Drop(tag=tag, attr="style", reason="style_rejected"))
    return tag, out, drops


def _fmt_open_tag(tag: str, attrs: dict[str, str]) -> str:
    """Render a safe opening tag with sorted, escaped attributes.

    Args:
        tag (str): Tag name.
        attrs (dict[str, str]): Escaped attribute map.

    Returns:
        str: Serialized ``<tag …>`` fragment.

    Examples:
        >>> _fmt_open_tag("p", {})
        '<p>'
    """

    if not attrs:
        return f"<{tag}>"
    inner = " ".join(f'{k}="{_escape_attr(v)}"' for k, v in sorted(attrs.items()))
    return f"<{tag} {inner}>"


def _escape_attr(val: str) -> str:
    """Escape attribute value text for double-quoted HTML attributes.

    Args:
        val (str): Raw attribute value.

    Returns:
        str: Escaped string safe for ``attr="…"`` embedding.

    Examples:
        >>> '"' not in _escape_attr('say "hi"')
        True
    """

    return (
        val.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _escape_text(data: str) -> str:
    """Escape free text for HTML body emission.

    Args:
        data (str): Raw text chunk.

    Returns:
        str: Escaped text safe outside tags.

    Examples:
        >>> "<" not in _escape_text("<evil>")
        True
    """

    return data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _SanitisingParser(HTMLParser):
    """Streaming allowlist parser that accumulates sanitised HTML."""

    def __init__(self) -> None:
        """Create parser state containers.

        Examples:
            >>> p = _SanitisingParser()
            >>> p._out == [] and p._skip_depth == 0
            True
        """

        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._drops: list[Drop] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Process an opening tag, appending markup or entering skip mode.

        Args:
            tag (str): Tag name from the lexer.
            attrs (list[tuple[str, str | None]]): Attribute tuples from ``HTMLParser``.

        Examples:
            >>> p = _SanitisingParser()
            >>> p.feed("<p>ok</p>")
            >>> p.close()
            >>> "ok" in "".join(p._out)
            True
        """

        t = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth += 1
            return
        if t in _GLOBAL_BANNED:
            self._drops.append(Drop(tag=t, reason="banned_tag"))
            self._skip_depth = 1
            return
        if t not in _ALLOWED_TAGS:
            self._drops.append(Drop(tag=t, reason="unknown_tag"))
            self._skip_depth = 1
            return
        _, filtered, drops = _filter_attrs(t, attrs)
        self._drops.extend(drops)
        void_tags = {"br", "hr", "input", "img"}
        if t in void_tags:
            self._out.append(_fmt_open_tag(t, filtered))
            return
        self._out.append(_fmt_open_tag(t, filtered))

    def handle_endtag(self, tag: str) -> None:
        """Emit closing tags when not skipping a banned subtree.

        Args:
            tag (str): Tag name from the lexer.

        Examples:
            >>> p = _SanitisingParser()
            >>> p.feed("<p></p>")
            >>> p.close()
            >>> "</p>" in "".join(p._out)
            True
        """

        t = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if t in _ALLOWED_TAGS and t not in {"br", "hr", "input", "img"}:
            self._out.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        """Append escaped character data outside skipped regions.

        Args:
            data (str): Text chunk between tags.

        Examples:
            >>> p = _SanitisingParser()
            >>> p.feed("<p>z</p>")
            >>> p.close()
            >>> "z" in "".join(p._out)
            True
        """

        if self._skip_depth > 0:
            return
        self._out.append(_escape_text(data))

    def handle_entityref(self, name: str) -> None:
        """Preserve named character references when not skipping.

        Args:
            name (str): Entity name without leading ``&``.

        Examples:
            >>> p = _SanitisingParser()
            >>> p.handle_entityref("amp")
            >>> "".join(p._out)
            '&amp;'
        """

        if self._skip_depth > 0:
            return
        self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        """Preserve numeric character references when not skipping.

        Args:
            name (str): Character reference body (decimal / hex).

        Examples:
            >>> p = _SanitisingParser()
            >>> p.handle_charref("65")
            >>> "".join(p._out)
            '&#65;'
        """

        if self._skip_depth > 0:
            return
        self._out.append(f"&#{name};")


def sanitise(html: str) -> SanitiseResult:
    """Return allowlisted HTML and a drop list (`specs/29-openui.md` §8.1).

    Args:
        html (str): Agent-authored HTML fragment.

    Returns:
        SanitiseResult: Sanitised HTML, drops, and byte stats.

    Examples:
        >>> "script" not in sanitise("<p>ok</p><script>x</script>").html
        True
    """

    parser = _SanitisingParser()
    parser.feed(html or "")
    parser.close()
    out_html = "".join(parser._out)
    stats = {
        "bytes_in": len((html or "").encode("utf-8")),
        "bytes_out": len(out_html.encode("utf-8")),
        "tags_dropped": len(parser._drops),
    }
    return SanitiseResult(html=out_html, dropped=list(parser._drops), stats=stats)


__all__ = ["sanitise"]
