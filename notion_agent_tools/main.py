"""Demo entrypoint for Notion AN-MD round-trip testing."""

from __future__ import annotations

from notion_agent_tools.agent_tools import AgentToolError, read_page, upsert_page


SAMPLE_MD = """# ТРПО: сложный конспект

Обычный текст с inline формулой $E=mc^2$ и ==желтым маркером==.

:::callout-blue [Важно для экзамена]
Внутри callout есть список:

1. Первый пункт с формулой $a^2 + b^2 = c^2$.
2. Второй пункт со вложенным toggle:

   :::toggle [Доказательство]
   Блочная формула:

   $$
   \\int_a^b f(x)dx = F(b) - F(a)
   $$

   - Вложенный маркированный список
   - Еще пункт с ==акцентом==
   :::
:::

:::toggle [Контрольный вопрос]
Почему regex-парсер ломается на таких структурах?
:::
"""


def main() -> None:
    page_title = "ТРПО: сложный конспект"
    try:
        url = upsert_page(page_title, SAMPLE_MD)
        markdown = read_page(page_title)
    except AgentToolError as exc:
        print(f"Notion round-trip failed: {exc}")
        return
    print(f"Uploaded Notion page: {url}")
    print("\n--- Round-trip AN-MD ---\n")
    print(markdown)


if __name__ == "__main__":
    main()
