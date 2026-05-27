"""Thin, agent-safe wrapper around the official Notion client."""

from __future__ import annotations

import random
import time
from collections.abc import Iterable
from typing import Any

from notion_client import APIResponseError, Client

from notion_agent_tools.core.config import get_config


NotionBlock = dict[str, Any]
NotionPage = dict[str, Any]

MAX_BLOCKS_PER_REQUEST = 100
MAX_RETRIES = 5
BASE_RETRY_DELAY_SECONDS = 1.0


class NotionClientError(RuntimeError):
    """Raised when a Notion API operation fails with an agent-readable message."""


class AmbiguousMatchError(NotionClientError):
    """Raised when a page title lookup matches more than one child page."""


class NotionCoreClient:
    """Core Notion API wrapper with pagination, chunking, and retry handling."""

    def __init__(self, token: str | None = None, notion: Client | None = None) -> None:
        """Create a Notion wrapper.

        Args:
            token: Explicit Notion token. If omitted, it is loaded from config.
            notion: Preconfigured client, mainly useful for tests.
        """

        if notion is not None:
            self.notion = notion
            return

        auth_token = token or get_config().notion_token
        self.notion = Client(auth=auth_token)

    def find_page_by_title(self, parent_page_id: str, title: str, exact: bool = True) -> str | None:
        """Find a child page by exact title or by a safe title prefix."""

        start_cursor: str | None = None
        matches: list[tuple[str, str]] = []
        try:
            while True:
                response = self._call_with_retry(
                    self.notion.blocks.children.list,
                    block_id=parent_page_id,
                    start_cursor=start_cursor,
                    page_size=100,
                )
                for block in response.get("results", []):
                    if block.get("type") != "child_page":
                        continue
                    page_title = block.get("child_page", {}).get("title", "")
                    if _title_matches(page_title, title, exact):
                        page_id = block.get("id")
                        if page_id:
                            matches.append((str(page_id), str(page_title)))

                if not response.get("has_more"):
                    if len(matches) > 1:
                        matched_titles = ", ".join(match_title for _, match_title in matches)
                        mode = "exact title" if exact else "title prefix"
                        raise AmbiguousMatchError(
                            f"Ambiguous Notion child page lookup by {mode} {title!r}: {matched_titles}"
                        )
                    return matches[0][0] if matches else None
                start_cursor = response.get("next_cursor")
        except APIResponseError as exc:
            raise _wrap_api_error("find child page", exc) from exc

    def clear_page_blocks(self, page_id: str) -> None:
        """Archive every top-level block under a page."""

        try:
            blocks = list(self.iter_child_blocks(page_id))
            for block in blocks:
                block_id = block.get("id")
                if block_id:
                    self._call_with_retry(self.notion.blocks.delete, block_id=block_id)
        except APIResponseError as exc:
            raise _wrap_api_error("clear page blocks", exc) from exc

    def append_blocks_chunked(self, block_id: str, blocks: list[NotionBlock]) -> None:
        """Append blocks under `block_id` in API-safe chunks of at most 100."""

        try:
            for chunk in _chunks(blocks, MAX_BLOCKS_PER_REQUEST):
                if not chunk:
                    continue
                response = self._call_with_retry(
                    self.notion.blocks.children.append,
                    block_id=block_id,
                    children=[_block_without_children(block) for block in chunk],
                )
                created_blocks = response.get("results", [])
                for source_block, created_block in zip(chunk, created_blocks, strict=False):
                    created_block_id = created_block.get("id")
                    nested_children = _block_children(source_block)
                    if isinstance(created_block_id, str) and nested_children:
                        self.append_blocks_chunked(created_block_id, nested_children)
        except APIResponseError as exc:
            raise _wrap_api_error("append blocks", exc) from exc

    def update_page_title(self, page_id: str, title: str) -> NotionPage:
        """Update the title of an existing child page."""

        try:
            return self._call_with_retry(
                self.notion.pages.update,
                page_id=page_id,
                properties=_title_properties(title),
            )
        except APIResponseError as exc:
            raise _wrap_api_error("update page title", exc) from exc

    def create_child_page(self, parent_page_id: str, title: str, blocks: list[NotionBlock]) -> NotionPage:
        """Create a child page and append blocks with API-safe recursive nesting."""

        try:
            page = self._call_with_retry(
                self.notion.pages.create,
                parent={"type": "page_id", "page_id": parent_page_id},
                properties=_title_properties(title),
            )
            self.append_blocks_chunked(str(page["id"]), blocks)
            return page
        except APIResponseError as exc:
            raise _wrap_api_error("create child page", exc) from exc

    def iter_child_blocks(self, block_id: str) -> Iterable[NotionBlock]:
        """Yield all direct children of `block_id` across Notion pagination."""

        start_cursor: str | None = None
        try:
            while True:
                response = self._call_with_retry(
                    self.notion.blocks.children.list,
                    block_id=block_id,
                    start_cursor=start_cursor,
                    page_size=100,
                )
                yield from response.get("results", [])
                if not response.get("has_more"):
                    return
                start_cursor = response.get("next_cursor")
        except APIResponseError as exc:
            raise _wrap_api_error("iterate child blocks", exc) from exc

    def _call_with_retry(self, func: Any, **kwargs: Any) -> Any:
        """Call a Notion API method with exponential backoff for transient failures."""

        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(**kwargs)
            except APIResponseError as exc:
                if not _is_retryable(exc) or attempt >= MAX_RETRIES:
                    raise
                retry_after = _retry_after_seconds(exc)
                delay = retry_after if retry_after is not None else BASE_RETRY_DELAY_SECONDS * (2**attempt)
                delay = delay * (0.8 + 0.4 * random.random())
                time.sleep(delay)

        raise NotionClientError("Notion API request failed after retries")


def _chunks(items: list[NotionBlock], size: int) -> Iterable[list[NotionBlock]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _block_children(block: NotionBlock) -> list[NotionBlock]:
    block_type = block.get("type")
    if not isinstance(block_type, str):
        return []
    body = block.get(block_type)
    if not isinstance(body, dict):
        return []
    children = body.get("children")
    return children if isinstance(children, list) else []


def _block_without_children(block: NotionBlock) -> NotionBlock:
    block_type = block.get("type")
    if not isinstance(block_type, str):
        return block.copy()

    clean_block = block.copy()
    body = block.get(block_type)
    if isinstance(body, dict) and "children" in body:
        clean_body = body.copy()
        clean_body.pop("children", None)
        clean_block[block_type] = clean_body
    return clean_block


def _title_properties(title: str) -> dict[str, Any]:
    return {
        "title": {
            "title": [
                {
                    "type": "text",
                    "text": {"content": title},
                }
            ]
        }
    }


def _title_matches(page_title: str, query: str, exact: bool) -> bool:
    if exact:
        return page_title == query
    if not page_title.startswith(query):
        return False
    if len(page_title) == len(query):
        return True
    if not query:
        return False
    return not query[-1].isalnum() or not page_title[len(query)].isalnum()


def _wrap_api_error(action: str, exc: APIResponseError) -> NotionClientError:
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", str(exc))
    details = f"status={status}, code={code}" if status or code else "unknown status"
    return NotionClientError(f"Failed to {action}: {message} ({details})")


def _is_retryable(exc: APIResponseError) -> bool:
    status = getattr(exc, "status", None)
    code = str(getattr(exc, "code", ""))
    return status in {429, 500, 502, 503, 504} or code == "rate_limited"


def _retry_after_seconds(exc: APIResponseError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
