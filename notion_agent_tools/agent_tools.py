"""High-level generic tools intended for LLM-agent use."""

from __future__ import annotations

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
        
        existing_page_id = client.find_page_by_title(target_parent_id, clean_title)

        if existing_page_id is not None:
            page = client.update_page_title(existing_page_id, clean_title)
            client.clear_page_blocks(existing_page_id)
            client.append_blocks_chunked(existing_page_id, blocks)
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
        page_id = client.find_page_by_title(target_parent_id, clean_title)
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
        page_id = client.find_page_by_title(target_parent_id, prefix)
        if page_id is None:
            return None
        return f"https://www.notion.so/{page_id.replace('-', '')}"
    except Exception:
        return None


def _page_url(page: dict[str, object]) -> str:
    url = page.get("url")
    if isinstance(url, str) and url:
        return url
    page_id = page.get("id")
    if isinstance(page_id, str) and page_id:
        return f"https://www.notion.so/{page_id.replace('-', '')}"
    raise AgentToolError("Notion response did not include page URL or page ID")
