"""Demo entrypoint for Notion AN-MD round-trip testing."""

from __future__ import annotations

from notion_agent_tools.agent_tools import AgentToolError, read_page, upsert_page
from notion_agent_tools.parsers.md_to_notion import markdown_to_notion


LONG_PARAGRAPH = (
    "Длинный абзац для проверки авто-дробления rich_text. "
    "Обычные символы разметки должны пережить round-trip как текст: "
    "\\*, \\_, \\$, \\=\\=, \\[, \\], \\\\. "
    * 35
)


SAMPLE_MD = f"""# Milestone 4: stability demo

{LONG_PARAGRAPH}

Обычный текст с inline формулой $E=mc^2$ и ==желтым маркером==.

```python
print("trailing newline is preserved")

```

:::callout-blue [Важно]
1. Первый пункт.
2. Второй пункт с вложенным toggle:

   :::toggle [Детали]
   Вложенность остается в поддерживаемом лимите.
   :::
:::
"""


def main() -> None:
    page_title = "Milestone 4: stability demo"
    blocks = markdown_to_notion(SAMPLE_MD)
    first_paragraph = next(block for block in blocks if block["type"] == "paragraph")
    chunks = first_paragraph["paragraph"]["rich_text"]
    max_chunk_length = max(len(item["plain_text"]) for item in chunks)

    try:
        url = upsert_page(page_title, SAMPLE_MD)
        markdown = read_page(page_title)
    except AgentToolError as exc:
        print(f"Notion round-trip failed: {exc}")
        return
    print(f"Uploaded Notion page: {url}")
    print(f"Long paragraph length: {len(LONG_PARAGRAPH)}")
    print(f"Generated rich_text chunks: {len(chunks)}")
    print(f"Max rich_text chunk length: {max_chunk_length}")
    print("\n--- Round-trip AN-MD ---\n")
    print(markdown)


if __name__ == "__main__":
    main()
