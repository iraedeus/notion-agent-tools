"""Application configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from os import getenv

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required NAT configuration is missing."""


@dataclass(frozen=True)
class NotionConfig:
    """Runtime settings for Notion API access."""

    notion_token: str
    notion_parent_page: str


@lru_cache(maxsize=1)
def get_config() -> NotionConfig:
    """Load Notion configuration from `.env` and process environment."""

    load_dotenv()
    notion_token = _required_env("NOTION_TOKEN")
    notion_parent_page = _required_env("NOTION_PARENT_PAGE")
    return NotionConfig(
        notion_token=notion_token,
        notion_parent_page=notion_parent_page,
    )


def _required_env(name: str) -> str:
    value = getenv(name)
    if value is None or not value.strip():
        raise ConfigError(f"Missing required environment variable: {name}")
    return value.strip()
