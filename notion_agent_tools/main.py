"""Live Milestone 4 round-trip stress test against Notion."""

from __future__ import annotations

from notion_agent_tools.agent_tools import AgentToolError, read_page, upsert_page
from notion_agent_tools.parsers.md_to_notion import markdown_to_notion


PAGE_TITLE = "Тест 4. Комплексная проверка NAT"

LONG_PARAGRAPH = (
    "Это сверхдлинный абзац для проверки автоматического дробления rich_text "
    "на безопасные фрагменты до 1800 символов внутри одного Notion-блока. "
    "Текст намеренно повторяется, чтобы пройти реальный API-лимит без ручной нарезки. "
    * 18
)


SAMPLE_MD = f"""# {PAGE_TITLE}

{LONG_PARAGRAPH}

:::callout-blue [Важный заголовок]
1. Элемент
   :::toggle [Доказательство]
   Внутри спойлера находится обычный текст и блочная формула.

   $$
   x^2 + y^2 = z^2
   $$
   :::
:::

Цена составляет $100 за штуку, а формула x_1 * y_2 может содержать звездочки и ==выделения== без вызова ошибок форматирования.

```python
def trailing_newlines() -> str:
    return "Notion should preserve blank lines below"


```
"""


def main() -> None:
    blocks = markdown_to_notion(SAMPLE_MD)
    first_paragraph = next(block for block in blocks if block["type"] == "paragraph")
    chunks = first_paragraph["paragraph"]["rich_text"]
    max_chunk_length = max(len(item["plain_text"]) for item in chunks)

    try:
        print("[1/4] Создание или первичная запись страницы в Notion...")
        url = upsert_page(PAGE_TITLE, SAMPLE_MD)
        print(f"Страница Notion: {url}")

        print("[2/4] Повторный upsert по exact title для проверки очистки и перезаписи...")
        url = upsert_page(PAGE_TITLE, SAMPLE_MD)
        print(f"Страница Notion после перезаписи: {url}")

        print("[3/4] Чтение страницы обратно через exact title...")
        markdown = read_page(PAGE_TITLE)
    except AgentToolError as exc:
        print(f"Live round-trip test failed: {exc}")
        _print_access_help(str(exc))
        return

    print("[4/4] Проверки локального payload перед отправкой:")
    print(f"Длина сверхдлинного абзаца: {len(LONG_PARAGRAPH)}")
    print(f"Количество rich_text чанков в первом абзаце: {len(chunks)}")
    print(f"Максимальная длина rich_text чанка: {max_chunk_length}")
    print("\n--- Финальный AN-MD из Notion ---\n")
    print(markdown)


def _print_access_help(error_message: str) -> None:
    lower_message = error_message.lower()
    access_markers = (
        "status=401",
        "status=403",
        "unauthorized",
        "restricted",
        "object_not_found",
    )
    if not any(marker in lower_message for marker in access_markers):
        return

    print("\nПохоже на проблему авторизации или доступа Notion.")
    print("Проверьте, что в .env указан актуальный NOTION_TOKEN.")
    print("Откройте родительскую страницу Notion, нажмите Share/Поделиться и добавьте вашу интеграцию.")
    print("Убедитесь, что NOTION_PARENT_PAGE содержит id именно этой родительской страницы.")


if __name__ == "__main__":
    main()
