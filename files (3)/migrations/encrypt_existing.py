"""
migrations/encrypt_existing.py
==============================
Одноразовая миграция: зашифровать ПДн, которые уже лежат в БД в открытом виде.

Идея: для каждого значения в name/phone/address пробуем decrypt. Если декодит
без ошибки — значит уже зашифровано (Fernet-токен). Если падает InvalidToken —
значит это plain text, шифруем и записываем обратно.

Перед запуском:
  1) Сделайте бэкап БД:  cp data/bot.db data/bot.db.bak
  2) Убедитесь, что в .env задан правильный FERNET_KEY
  3) python migrations/encrypt_existing.py

Скрипт идемпотентен — повторный запуск не сломает уже зашифрованные данные.
"""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

# Поднимаем sys.path, чтобы импортировать crypto_utils и config из корня.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_PATH                                  # noqa: E402
from crypto_utils import encrypt, decrypt                   # noqa: E402
from cryptography.fernet import InvalidToken                # noqa: E402


def is_already_encrypted(value: str) -> bool:
    """Проверка: значение уже зашифровано Fernet-ом?"""
    if value is None or value == "":
        return True  # нечего шифровать
    try:
        decrypt(value)
        return True
    except (InvalidToken, ValueError, TypeError):
        return False


def migrate() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, phone, address FROM users")
    rows = cursor.fetchall()

    total = len(rows)
    encrypted_fields = 0
    untouched_users = 0

    print(f"Найдено пользователей: {total}")

    for row in rows:
        user_id = row["id"]
        updates = {}

        for field in ("name", "phone", "address"):
            value = row[field]
            if value is None or value == "":
                continue
            if not is_already_encrypted(value):
                updates[field] = encrypt(value)
                encrypted_fields += 1

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [user_id]
            cursor.execute(f"UPDATE users SET {set_clause} WHERE id = ?", params)
            print(f"  user_id={user_id}: зашифровано полей — {len(updates)}")
        else:
            untouched_users += 1

    conn.commit()
    conn.close()

    print()
    print("─" * 60)
    print(f"Готово. Полей зашифровано: {encrypted_fields}")
    print(f"Пользователей, у которых всё уже было ОК: {untouched_users}")
    print("─" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("Миграция шифрования ПДн")
    print(f"БД: {DB_PATH}")
    print("=" * 60)
    print()
    answer = input("Сделали бэкап БД? (yes/no): ").strip().lower()
    if answer != "yes":
        print("Отмена. Сначала сделайте бэкап: cp data/bot.db data/bot.db.bak")
        sys.exit(1)
    migrate()