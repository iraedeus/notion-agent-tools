"""AN-MD parser based on markdown-it-py tokens.

The parser extends CommonMark with:
- Notion-like containers: :::callout-blue [Title] ... ::: and :::toggle [Title] ... :::
- inline and block LaTeX math: $...$ and $$...$$
- yellow highlights: ==text==
"""

from __future__ import annotations

from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token


CONTAINER_MARKER = ":::"


@dataclass(frozen=True)
class ContainerSpec:
    """Parsed opening line for an AN-MD container."""

    kind: str
    color: str | None
    title: str | None


def create_markdown_parser() -> MarkdownIt:
    """Create a MarkdownIt parser configured for Agent-Notion Markdown."""

    md = MarkdownIt("commonmark", {"html": False, "breaks": False})
    md.enable("table")

    md.block.ruler.before(
        "fence",
        "an_container",
        _container_block_rule,
        {"alt": ["paragraph", "reference", "blockquote", "list"]},
    )
    md.block.ruler.before(
        "fence",
        "math_block",
        _math_block_rule,
        {"alt": ["paragraph", "reference", "blockquote", "list"]},
    )
    md.inline.ruler.before("escape", "math_inline", _math_inline_rule)
    md.inline.ruler.before("emphasis", "mark_inline", _mark_inline_rule)
    return md


def parse_markdown(md_text: str) -> list[Token]:
    """Parse AN-MD into markdown-it-py tokens."""

    return create_markdown_parser().parse(md_text)


def _container_block_rule(
    state: StateBlock,
    start_line: int,
    end_line: int,
    silent: bool,
) -> bool:
    start_pos = state.bMarks[start_line] + state.tShift[start_line]
    max_pos = state.eMarks[start_line]
    line_text = state.src[start_pos:max_pos].strip()

    spec = _parse_container_open(line_text)
    if spec is None:
        return False
    if silent:
        return True

    next_line = start_line + 1
    nested_level = 0
    auto_closed = False

    while next_line < end_line:
        line_start = state.bMarks[next_line] + state.tShift[next_line]
        line_end = state.eMarks[next_line]
        candidate = state.src[line_start:line_end].strip()

        if candidate == CONTAINER_MARKER:
            if nested_level == 0:
                auto_closed = True
                break
            nested_level -= 1
        elif _parse_container_open(candidate) is not None:
            nested_level += 1

        next_line += 1

    old_parent = state.parentType
    old_line_max = state.lineMax
    state.parentType = "an_container"
    state.lineMax = next_line

    token = state.push("an_container_open", "div", 1)
    token.block = True
    token.map = [start_line, next_line]
    token.markup = CONTAINER_MARKER
    token.meta = {"kind": spec.kind, "color": spec.color, "title": spec.title}

    state.md.block.tokenize(state, start_line + 1, next_line)

    token = state.push("an_container_close", "div", -1)
    token.block = True
    token.markup = CONTAINER_MARKER

    state.parentType = old_parent
    state.lineMax = old_line_max
    state.line = next_line + 1 if auto_closed else next_line
    return True


def _parse_container_open(line_text: str) -> ContainerSpec | None:
    if not line_text.startswith(CONTAINER_MARKER):
        return None

    body = line_text[len(CONTAINER_MARKER) :].strip()
    if not body:
        return None

    name, _, title_part = body.partition(" ")
    title = _parse_optional_title(title_part.strip())

    if name == "toggle":
        return ContainerSpec(kind="toggle", color=None, title=title)

    prefix = "callout"
    if name == prefix:
        return ContainerSpec(kind="callout", color=None, title=title)
    if name.startswith(f"{prefix}-") and len(name) > len(prefix) + 1:
        return ContainerSpec(kind="callout", color=name[len(prefix) + 1 :], title=title)

    return None


def _parse_optional_title(value: str) -> str | None:
    if not value:
        return None
    if value.startswith("[") and value.endswith("]") and len(value) >= 2:
        return value[1:-1].strip() or None
    return value


def _math_block_rule(
    state: StateBlock,
    start_line: int,
    end_line: int,
    silent: bool,
) -> bool:
    start_pos = state.bMarks[start_line] + state.tShift[start_line]
    max_pos = state.eMarks[start_line]
    first_line = state.src[start_pos:max_pos].strip()

    if not first_line.startswith("$$"):
        return False
    if silent:
        return True

    first_content = first_line[2:]
    content_lines: list[str] = []
    next_line = start_line
    closed = False

    if first_content.endswith("$$") and len(first_content) > 2:
        content_lines.append(first_content[:-2].strip())
        closed = True
    else:
        if first_content.strip():
            content_lines.append(first_content)
        next_line = start_line + 1
        while next_line < end_line:
            line_start = state.bMarks[next_line] + state.tShift[next_line]
            line_end = state.eMarks[next_line]
            line_text = state.src[line_start:line_end]
            stripped = line_text.strip()
            if stripped.endswith("$$"):
                closing_index = line_text.rfind("$$")
                before_close = line_text[:closing_index]
                if before_close.strip():
                    content_lines.append(before_close)
                closed = True
                break
            content_lines.append(line_text)
            next_line += 1

    token = state.push("math_block", "math", 0)
    token.block = True
    token.content = "\n".join(content_lines).strip()
    token.map = [start_line, next_line + 1]
    token.markup = "$$"

    state.line = next_line + 1 if closed else next_line
    return True


def _math_inline_rule(state: StateInline, silent: bool) -> bool:
    start = state.pos
    src = state.src
    if src[start] != "$" or src.startswith("$$", start):
        return False

    end = _find_unescaped(src, "$", start + 1)
    if end < 0:
        return False
    if end == start + 1:
        return False
    if silent:
        return True

    token = state.push("math_inline", "math", 0)
    token.markup = "$"
    token.content = src[start + 1 : end]
    state.pos = end + 1
    return True


def _mark_inline_rule(state: StateInline, silent: bool) -> bool:
    start = state.pos
    src = state.src
    if not src.startswith("==", start):
        return False

    end = src.find("==", start + 2)
    if end < 0 or end == start + 2:
        return False
    if silent:
        return True

    token = state.push("mark_open", "mark", 1)
    token.markup = "=="

    old_pos = state.pos
    old_pos_max = state.posMax
    state.pos = start + 2
    state.posMax = end
    state.md.inline.tokenize(state)
    state.pos = old_pos
    state.posMax = old_pos_max

    token = state.push("mark_close", "mark", -1)
    token.markup = "=="
    state.pos = end + 2
    return True


def _find_unescaped(src: str, char: str, start: int) -> int:
    pos = start
    while True:
        pos = src.find(char, pos)
        if pos < 0:
            return -1
        if pos == 0 or src[pos - 1] != "\\":
            return pos
        pos += 1
