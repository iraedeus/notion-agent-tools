"""Convert AN-MD markdown-it-py tokens to Notion block dictionaries."""

from __future__ import annotations

from typing import Any

from markdown_it.token import Token

from notion_agent_tools.parsers.md_ast import parse_markdown


NotionBlock = dict[str, Any]
RichText = dict[str, Any]

_OPEN_TO_CLOSE = {
    "paragraph_open": "paragraph_close",
    "heading_open": "heading_close",
    "bullet_list_open": "bullet_list_close",
    "ordered_list_open": "ordered_list_close",
    "list_item_open": "list_item_close",
    "blockquote_open": "blockquote_close",
    "an_container_open": "an_container_close",
}

_COLOR_MAP = {
    "blue": "blue_background",
    "brown": "brown_background",
    "gray": "gray_background",
    "green": "green_background",
    "orange": "orange_background",
    "pink": "pink_background",
    "purple": "purple_background",
    "red": "red_background",
    "yellow": "yellow_background",
}


def markdown_to_notion(md_text: str) -> list[NotionBlock]:
    """Convert AN-MD text into Notion API block payloads."""

    tokens = parse_markdown(md_text)
    blocks, _ = _parse_blocks(tokens, 0)
    return blocks


def _parse_blocks(tokens: list[Token], index: int, stop_type: str | None = None) -> tuple[list[NotionBlock], int]:
    blocks: list[NotionBlock] = []

    while index < len(tokens):
        token = tokens[index]
        if stop_type and token.type == stop_type:
            return blocks, index + 1

        if token.type == "paragraph_open":
            block, index = _parse_paragraph(tokens, index)
            if block is not None:
                blocks.append(block)
            continue

        if token.type == "heading_open":
            block, index = _parse_heading(tokens, index)
            blocks.append(block)
            continue

        if token.type in {"bullet_list_open", "ordered_list_open"}:
            list_blocks, index = _parse_list(tokens, index)
            blocks.extend(list_blocks)
            continue

        if token.type == "blockquote_open":
            block, index = _parse_blockquote(tokens, index)
            blocks.append(block)
            continue

        if token.type == "an_container_open":
            block, index = _parse_container(tokens, index)
            blocks.append(block)
            continue

        if token.type == "math_block":
            blocks.append(_equation_block(token.content))
            index += 1
            continue

        if token.type in {"fence", "code_block"}:
            blocks.append(_code_block(token.content, token.info))
            index += 1
            continue

        if token.type == "hr":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            index += 1
            continue

        index += 1

    return blocks, index


def _parse_paragraph(tokens: list[Token], index: int) -> tuple[NotionBlock | None, int]:
    inline_token = tokens[index + 1] if index + 1 < len(tokens) else None
    rich_text = _inline_to_rich_text(inline_token.children or []) if inline_token and inline_token.type == "inline" else []
    next_index = _skip_to_close(tokens, index, "paragraph_close")
    if not rich_text:
        return None, next_index
    return _text_block("paragraph", rich_text), next_index


def _parse_heading(tokens: list[Token], index: int) -> tuple[NotionBlock, int]:
    token = tokens[index]
    level = int(token.tag[1]) if token.tag.startswith("h") and token.tag[1:].isdigit() else 1
    notion_type = f"heading_{min(level, 3)}"
    inline_token = tokens[index + 1] if index + 1 < len(tokens) else None
    rich_text = _inline_to_rich_text(inline_token.children or []) if inline_token and inline_token.type == "inline" else []
    return _text_block(notion_type, rich_text), _skip_to_close(tokens, index, "heading_close")


def _parse_list(tokens: list[Token], index: int) -> tuple[list[NotionBlock], int]:
    list_type = "bulleted_list_item" if tokens[index].type == "bullet_list_open" else "numbered_list_item"
    close_type = _OPEN_TO_CLOSE[tokens[index].type]
    index += 1
    items: list[NotionBlock] = []

    while index < len(tokens) and tokens[index].type != close_type:
        if tokens[index].type != "list_item_open":
            index += 1
            continue
        item_block, index = _parse_list_item(tokens, index, list_type)
        items.append(item_block)

    return items, index + 1


def _parse_list_item(tokens: list[Token], index: int, list_type: str) -> tuple[NotionBlock, int]:
    index += 1
    rich_text: list[RichText] = []
    children: list[NotionBlock] = []

    if index < len(tokens) and tokens[index].type == "paragraph_open":
        inline_token = tokens[index + 1] if index + 1 < len(tokens) else None
        rich_text = _inline_to_rich_text(inline_token.children or []) if inline_token and inline_token.type == "inline" else []
        index = _skip_to_close(tokens, index, "paragraph_close")

    children, index = _parse_blocks(tokens, index, "list_item_close")
    block = _text_block(list_type, rich_text)
    if children:
        block[list_type]["children"] = children
    return block, index


def _parse_blockquote(tokens: list[Token], index: int) -> tuple[NotionBlock, int]:
    children, next_index = _parse_blocks(tokens, index + 1, "blockquote_close")
    if children and children[0]["type"] == "paragraph":
        rich_text = children[0]["paragraph"]["rich_text"]
        nested = children[1:]
    else:
        rich_text = []
        nested = children
    block = _text_block("quote", rich_text)
    if nested:
        block["quote"]["children"] = nested
    return block, next_index


def _parse_container(tokens: list[Token], index: int) -> tuple[NotionBlock, int]:
    token = tokens[index]
    meta = token.meta or {}
    kind = meta.get("kind")
    children, next_index = _parse_blocks(tokens, index + 1, "an_container_close")

    if kind == "toggle":
        rich_text = _plain_rich_text(meta.get("title") or "Toggle")
        block = _text_block("toggle", rich_text)
        if children:
            block["toggle"]["children"] = children
        return block, next_index

    title = meta.get("title")
    color = _COLOR_MAP.get(meta.get("color") or "", "default")
    rich_text = _plain_rich_text(title) if title else []
    block = _text_block("callout", rich_text)
    block["callout"]["icon"] = {"type": "emoji", "emoji": "💡"}
    block["callout"]["color"] = color
    if children:
        block["callout"]["children"] = children
    return block, next_index


def _inline_to_rich_text(tokens: list[Token]) -> list[RichText]:
    rich_text: list[RichText] = []
    annotations = _default_annotations()
    _append_inline_tokens(tokens, rich_text, annotations)
    return rich_text


def _append_inline_tokens(tokens: list[Token], output: list[RichText], annotations: dict[str, Any]) -> None:
    stack: list[dict[str, Any]] = [annotations.copy()]

    for token in tokens:
        current = stack[-1]

        if token.type == "text":
            output.append(_text_rich_text(token.content, current))
        elif token.type == "softbreak":
            output.append(_text_rich_text("\n", current))
        elif token.type == "hardbreak":
            output.append(_text_rich_text("\n", current))
        elif token.type == "code_inline":
            next_annotations = current.copy()
            next_annotations["code"] = True
            output.append(_text_rich_text(token.content, next_annotations))
        elif token.type == "math_inline":
            output.append(_equation_rich_text(token.content))
        elif token.type in {"strong_open", "em_open", "s_open", "mark_open"}:
            next_annotations = current.copy()
            if token.type == "strong_open":
                next_annotations["bold"] = True
            elif token.type == "em_open":
                next_annotations["italic"] = True
            elif token.type == "s_open":
                next_annotations["strikethrough"] = True
            elif token.type == "mark_open":
                next_annotations["color"] = "yellow_background"
            stack.append(next_annotations)
        elif token.type in {"strong_close", "em_close", "s_close", "mark_close"} and len(stack) > 1:
            stack.pop()
        elif token.children:
            _append_inline_tokens(token.children, output, current)


def _text_block(block_type: str, rich_text: list[RichText]) -> NotionBlock:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": rich_text},
    }


def _equation_block(expression: str) -> NotionBlock:
    return {
        "object": "block",
        "type": "equation",
        "equation": {"expression": expression},
    }


def _code_block(content: str, info: str) -> NotionBlock:
    language = (info or "plain text").strip().split(maxsplit=1)[0]
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": _plain_rich_text(content.rstrip("\n")),
            "language": language or "plain text",
        },
    }


def _plain_rich_text(content: str) -> list[RichText]:
    return [_text_rich_text(content, _default_annotations())] if content else []


def _text_rich_text(content: str, annotations: dict[str, Any]) -> RichText:
    return {
        "type": "text",
        "text": {"content": content, "link": None},
        "annotations": annotations.copy(),
        "plain_text": content,
        "href": None,
    }


def _equation_rich_text(expression: str) -> RichText:
    return {
        "type": "equation",
        "equation": {"expression": expression},
        "annotations": _default_annotations(),
        "plain_text": expression,
        "href": None,
    }


def _default_annotations() -> dict[str, Any]:
    return {
        "bold": False,
        "italic": False,
        "strikethrough": False,
        "underline": False,
        "code": False,
        "color": "default",
    }


def _skip_to_close(tokens: list[Token], index: int, close_type: str) -> int:
    open_type = tokens[index].type
    depth = 0
    while index < len(tokens):
        token_type = tokens[index].type
        if token_type == open_type:
            depth += 1
        elif token_type == close_type:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index
