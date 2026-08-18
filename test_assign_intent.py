"""Юнит-тесты: распределение заметок по проектам из чата (ADR-0017).

Проверяет _has_assign_intent (маркер [ASSIGN:] уважается только при явной
просьбе разложить по проектам) и _parse_assign_plan (разбор маркера).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.routes.chat import (  # noqa: E402
    _has_assign_intent,
    _parse_assign_plan,
)

INTENT_CASES = [
    # (текст сообщения, ожидаемое решение)
    ("разложи мои заметки по проектам", True),
    ("разложите всё по проектам", True),
    ("разложи по папкам", True),
    ("распредели заметки по проектам", True),
    ("распределить последние заметки", True),
    ("раскидай их по проектам", True),
    ("раскидай по папкам", True),
    ("разнеси заметки по темам-проектам", True),
    ("разбей заметки по папкам", True),
    ("сгруппируй по папкам", True),
    ("рассортируй заметки по проектам", True),
    ("сортируй по папкам", True),
    ("привяжи к проекту заметки о книге", True),
    ("привяжи к папке", True),
    ("отсортируй по проектам", True),
    ("сортировать по проектам", True),
    ("сортировать по папкам", True),
    ("сделай распределение по проектам", True),
    ("как бы ты разложила заметки по проектам", False),
    ("можно ли разложить их по проектам?", False),
    ("что если разложить всё по проектам", False),
    ("предложи, куда разложить заметки", False),
    ("расскажи про мои проекты", False),
    ("привет", False),
    ("это важно", False),
]

PARSE_CASES = [
    # (текст ответа, ожидаемый план)
    ('[ASSIGN:{"12": 5, "15": "Здоровье"}]', {12: 5, 15: "Здоровье"}),
    ('[ASSIGN:{"12":5}] [ASSIGN:{"15":"Бизнес"}]', {12: 5, 15: "Бизнес"}),
    ("просто текст без маркера", {}),
    ("[ASSIGN:{битый json}]", {}),
    ('[ASSIGN:{"12": 0}]', {}),
    ('[ASSIGN:{"12": "  "}]', {}),
    ('[ASSIGN:{"abc": 5}]', {}),
    ('текст [ASSIGN:{"12": 5}] ещё текст', {12: 5}),
]


def main() -> int:
    failed = 0
    print("--- intent ---")
    for text, expected in INTENT_CASES:
        got = _has_assign_intent(text)
        if got != expected:
            failed += 1
        print(
            f"{'OK' if got == expected else 'FAIL'}  {text!r} -> {got} (expected {expected})"
        )
    print("--- parse ---")
    for text, expected in PARSE_CASES:
        got = _parse_assign_plan(text)
        if got != expected:
            failed += 1
        print(
            f"{'OK' if got == expected else 'FAIL'}  {text!r} -> {got} (expected {expected})"
        )
    total = len(INTENT_CASES) + len(PARSE_CASES)
    if failed:
        print(f"\nFAILED: {failed}/{total}")
        return 1
    print(f"\nPASSED: {total}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
