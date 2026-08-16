"""Юнит-тесты: защита от самовольного сохранения заметок.

Проверяет _has_save_intent: маркер [SAVE:] бэкенд уважает только при явной
просьбе пользователя сохранить.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.routes.chat import _has_save_intent  # noqa: E402

CASES = [
    # (текст сообщения, ожидаемое решение)
    ("сохрани это", True),
    ("запиши в заметки", True),
    ("запомни на будущее", True),
    ("занеси в дневник", True),
    ("сделай заметку про это", True),
    ("save this", True),
    ("сохраню на потом", True),
    ("это важно", False),
    ("идея для блога", False),
    ("надо запомнить", False),
    ("нужно запомнить", False),
    ("стоит запомнить", False),
    ("хочу запомнить эту мысль", False),
    ("расскажи про медиа бренд", False),
    ("просто читаю текст", False),
    ("привет", False),
]


def main() -> int:
    failed = 0
    for text, expected in CASES:
        got = _has_save_intent(text)
        status = "OK" if got == expected else "FAIL"
        if got != expected:
            failed += 1
        print(f"{status}  {text!r} -> {got} (expected {expected})")
    if failed:
        print(f"\nFAILED: {failed}/{len(CASES)}")
        return 1
    print(f"\nPASSED: {len(CASES)}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
