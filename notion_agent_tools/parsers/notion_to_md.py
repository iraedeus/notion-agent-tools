"""Convert Notion block dictionaries back to Agent-Notion Markdown."""

from __future__ import annotations

from typing import Any

from notion_agent_tools.core.client import NotionBlock, NotionCoreClient


RichText = dict[str, Any]


def notion_to_markdown(blocks: list[NotionBlock], client: NotionCoreClient) -> str:
    """Convert Notion blocks into AN-MD Markdown.

    Nested block content is fetched lazily through `client.iter_child_blocks`
    whenever a block has `has_children=True`.
    """

    return _join_blocks(_render_blocks(blocks, client, indent=0)).strip("\n")


def rich_text_to_markdown(rich_text: list[RichText]) -> str:
    """Convert Notion rich_text objects into inline Markdown."""

    return "".join(_rich_text_item_to_markdown(item) for item in rich_text)


def _render_blocks(blocks: list[NotionBlock], client: NotionCoreClient, indent: int) -> list[str]:
    rendered: list[str] = []
    for block in blocks:
        markdown = _render_block(block, client, indent)
        if markdown is not None:
            rendered.append(markdown)
    return rendered


def _render_block(block: NotionBlock, client: NotionCoreClient, indent: int) -> str | None:
    block_type = block.get("type")
    spaces = " " * indent

    if block_type == "paragraph":
        text = _block_rich_text(block, "paragraph")
        return f"{spaces}{text}" if text else ""

    if block_type in {"heading_1", "heading_2", "heading_3"}:
        level = int(str(block_type).rsplit("_", maxsplit=1)[-1])
        text = _block_rich_text(block, str(block_type))
        return f"{spaces}{'#' * level} {text}".rstrip()

    if block_type == "divider":
        return f"{spaces}---"

    if block_type == "bulleted_list_item":
        return _render_list_item(block, client, "bulleted_list_item", "-", indent)

    if block_type == "numbered_list_item":
        return _render_list_item(block, client, "numbered_list_item", "1.", indent)

    if block_type == "equation":
        expression = str(block.get("equation", {}).get("expression", "")).strip()
        return f"{spaces}$$\n{spaces}{expression}\n{spaces}$$"

    if block_type == "code":
        code = block.get("code", {})
        language = str(code.get("language") or "").strip()
        text = _rich_text_to_plain_text(code.get("rich_text", []))
        fence = f"```{language}" if language and language != "plain text" else "```"
        return f"{spaces}{fence}\n{_indent_text(text, indent)}\n{spaces}```"

    if block_type == "quote":
        return _render_quote(block, client, indent)

    if block_type == "callout":
        return _render_callout(block, client, indent)

    if block_type == "toggle":
        return _render_toggle(block, client, indent)

    return _render_unsupported_children(block, client, indent)


def _render_list_item(
    block: NotionBlock,
    client: NotionCoreClient,
    block_type: str,
    marker: str,
    indent: int,
) -> str:
    spaces = " " * indent
    text = _block_rich_text(block, block_type)
    lines = [f"{spaces}{marker} {text}".rstrip()]
    children = _child_markdown(block, client, indent + 3)
    if children:
        lines.append(children)
    return "\n".join(lines)


def _render_quote(block: NotionBlock, client: NotionCoreClient, indent: int) -> str:
    text = _block_rich_text(block, "quote")
    child_text = _child_markdown(block, client, indent)
    content_parts = [part for part in [text, child_text] if part]
    content = "\n".join(content_parts)
    spaces = " " * indent
    if not content:
        return f"{spaces}>"
    return "\n".join(f"{spaces}> {line}" if line else f"{spaces}>" for line in content.splitlines())


def _render_callout(block: NotionBlock, client: NotionCoreClient, indent: int) -> str:
    callout = block.get("callout", {})
    title = rich_text_to_markdown(callout.get("rich_text", []))
    color = _callout_color(str(callout.get("color") or "default"))
    marker = f":::callout-{color}" if color else ":::callout"
    return _render_container(marker, title, block, client, indent)


def _render_toggle(block: NotionBlock, client: NotionCoreClient, indent: int) -> str:
    title = _block_rich_text(block, "toggle") or "Toggle"
    return _render_container(":::toggle", title, block, client, indent)


def _render_container(
    marker: str,
    title: str,
    block: NotionBlock,
    client: NotionCoreClient,
    indent: int,
) -> str:
    spaces = " " * indent
    opener = f"{spaces}{marker}"
    if title:
        opener = f"{opener} [{title}]"
    body = _child_markdown(block, client, indent)
    if body:
        return f"{opener}\n{body}\n{spaces}:::"
    return f"{opener}\n{spaces}:::"


def _render_unsupported_children(block: NotionBlock, client: NotionCoreClient, indent: int) -> str | None:
    child_text = _child_markdown(block, client, indent)
    return child_text or None


def _child_markdown(block: NotionBlock, client: NotionCoreClient, indent: int) -> str:
    if not block.get("has_children"):
        return ""

    block_id = block.get("id")
    if not isinstance(block_id, str) or not block_id:
        return ""

    children = list(client.iter_child_blocks(block_id))
    return _join_blocks(_render_blocks(children, client, indent)).strip("\n")


def _join_blocks(blocks: list[str]) -> str:
    if not blocks:
        return ""

    parts: list[str] = []
    previous_was_list = False
    for block in blocks:
        current_is_list = _starts_with_list_marker(block)
        if parts:
            parts.append("\n" if previous_was_list and current_is_list else "\n\n")
        parts.append(block)
        previous_was_list = current_is_list
    return "".join(parts)


def _starts_with_list_marker(markdown: str) -> bool:
    stripped = markdown.lstrip()
    return stripped.startswith("- ") or stripped.startswith("1. ")


def _block_rich_text(block: NotionBlock, block_type: str) -> str:
    value = block.get(block_type, {})
    rich_text = value.get("rich_text", []) if isinstance(value, dict) else []
    return rich_text_to_markdown(rich_text)


def _rich_text_item_to_markdown(item: RichText) -> str:
    item_type = item.get("type")
    if item_type == "equation":
        expression = str(item.get("equation", {}).get("expression", ""))
        return f"${expression}$"

    text_data = item.get("text", {}) if isinstance(item.get("text"), dict) else {}
    content = str(text_data.get("content") or item.get("plain_text") or "")
    if not content:
        return ""

    link_data = text_data.get("link")
    link_url = link_data.get("url") if isinstance(link_data, dict) else None
    href = item.get("href") or link_url
    annotations = item.get("annotations", {})
    if not annotations.get("code"):
        content = _escape_markdown_text(content)
    content = _apply_annotations(content, annotations)
    if isinstance(href, str) and href:
        return f"[{content}]({href})"
    return content


def _rich_text_to_plain_text(rich_text: list[RichText]) -> str:
    return "".join(_rich_text_item_to_plain_text(item) for item in rich_text)


def _rich_text_item_to_plain_text(item: RichText) -> str:
    if item.get("type") == "equation":
        return str(item.get("equation", {}).get("expression", ""))
    text_data = item.get("text", {}) if isinstance(item.get("text"), dict) else {}
    return str(text_data.get("content") or item.get("plain_text") or "")


def _apply_annotations(content: str, annotations: dict[str, Any]) -> str:
    if annotations.get("code"):
        content = f"`{content}`"
    if annotations.get("bold"):
        content = f"**{content}**"
    if annotations.get("italic"):
        content = f"*{content}*"
    if annotations.get("strikethrough"):
        content = f"~~{content}~~"
    if annotations.get("color") == "yellow_background":
        content = f"=={content}=="
    return content


def _callout_color(color: str) -> str:
    if color in {"default", ""}:
        return ""
    return color.removesuffix("_background")


def _escape_markdown_text(content: str) -> str:
    content = content.replace("\\", "\\\\")
    content = content.replace("==", "\\=\\=")
    for char in ("*", "_", "$", "[", "]"):
        content = content.replace(char, f"\\{char}")
    return content


def _indent_text(text: str, indent: int) -> str:
    spaces = " " * indent
    return "\n".join(f"{spaces}{line}" if line else "" for line in text.splitlines())
