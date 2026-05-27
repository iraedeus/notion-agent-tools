"""High-level generic tools intended for LLM-agent use."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from notion_agent_tools.core.client import (
    MAX_BLOCKS_PER_REQUEST,
    NotionClientError,
    NotionCoreClient,
)
from notion_agent_tools.core.config import ConfigError, get_config
from notion_agent_tools.parsers.md_to_notion import markdown_to_notion
from notion_agent_tools.parsers.notion_to_md import notion_to_markdown


class AgentToolError(RuntimeError):
    """Raised when an agent-facing tool cannot complete safely."""


def upsert_page(title: str, markdown_content: str, parent_id: str | None = None) -> str:
    """Create or overwrite a Notion page under parent_id using AN-MD content.

    Existing pages are matched by the exact title. If a match is found,
    its blocks are cleared and replaced.
    """

    clean_title = title.strip()
    if not clean_title:
        raise AgentToolError("Page title must not be empty")

    try:
        target_parent_id = parent_id or get_config().notion_parent_page
        blocks = markdown_to_notion(markdown_content)
        client = NotionCoreClient()

        existing_page_id = client.find_page_by_title(target_parent_id, clean_title, exact=True)

        if existing_page_id is not None:
            page = client.update_page_title(existing_page_id, clean_title)
            client.clear_page_blocks(existing_page_id)
            try:
                client.append_blocks_chunked(existing_page_id, blocks)
            except Exception as exc:
                backup_path = _write_failed_upsert_backup(
                    title=clean_title,
                    parent_id=target_parent_id,
                    page_id=existing_page_id,
                    markdown_content=markdown_content,
                    blocks=blocks,
                    error=exc,
                )
                raise AgentToolError(
                    "Failed to append Notion blocks after clearing existing page. "
                    f"Content backup was written to {backup_path}: {exc}"
                ) from exc
            return _page_url(page)

        page = client.create_child_page(
            parent_page_id=target_parent_id,
            title=clean_title,
            blocks=blocks,
        )
        remaining_blocks = blocks[MAX_BLOCKS_PER_REQUEST:]
        if remaining_blocks:
            page_id = str(page["id"])
            client.append_blocks_chunked(page_id, remaining_blocks)
        return _page_url(page)
    except AgentToolError:
        raise
    except (ConfigError, NotionClientError) as exc:
        raise AgentToolError(str(exc)) from exc
    except Exception as exc:
        raise AgentToolError(f"Failed to upsert Notion page: {exc}") from exc


def read_page(title: str, parent_id: str | None = None) -> str:
    """Read a Notion page by its exact title and return its content as AN-MD Markdown."""

    clean_title = title.strip()
    if not clean_title:
        raise AgentToolError("Page title must not be empty")

    try:
        target_parent_id = parent_id or get_config().notion_parent_page
        client = NotionCoreClient()
        page_id = client.find_page_by_title(target_parent_id, clean_title, exact=True)
        if page_id is None:
            raise AgentToolError(f"Page not found: {clean_title}")

        blocks = list(client.iter_child_blocks(page_id))
        return notion_to_markdown(blocks, client)
    except AgentToolError:
        raise
    except (ConfigError, NotionClientError) as exc:
        raise AgentToolError(str(exc)) from exc
    except Exception as exc:
        raise AgentToolError(f"Failed to read Notion page: {exc}") from exc


def find_page_url(title_prefix: str, parent_id: str | None = None) -> str | None:
    """Find a page under parent_id by a prefix of its title and return its URL.

    Returns None if no matching page is found. This enables agents to dynamically
    build hyperlinks, tables of contents, or navigation directly in Markdown.
    """
    prefix = title_prefix.strip()
    if not prefix:
        return None

    try:
        target_parent_id = parent_id or get_config().notion_parent_page
        client = NotionCoreClient()
        page_id = client.find_page_by_title(target_parent_id, prefix, exact=False)
        if page_id is None:
            return None
        return f"https://www.notion.so/{page_id.replace('-', '')}"
    except (ConfigError, NotionClientError) as exc:
        raise AgentToolError(str(exc)) from exc


def _page_url(page: dict[str, object]) -> str:
    url = page.get("url")
    if isinstance(url, str) and url:
        return url
    page_id = page.get("id")
    if isinstance(page_id, str) and page_id:
        return f"https://www.notion.so/{page_id.replace('-', '')}"
    raise AgentToolError("Notion response did not include page URL or page ID")


def _write_failed_upsert_backup(
    title: str,
    parent_id: str,
    page_id: str,
    markdown_content: str,
    blocks: list[dict[str, Any]],
    error: BaseException,
) -> Path:
    backup_dir = Path("notion_upsert_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "_", title).strip("_") or "untitled"
    backup_path = backup_dir / f"{timestamp}_{safe_title}.json"
    payload = {
        "title": title,
        "parent_id": parent_id,
        "page_id": page_id,
        "markdown_content": markdown_content,
        "blocks": blocks,
        "error": repr(error),
        "created_at": timestamp,
    }
    backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path
