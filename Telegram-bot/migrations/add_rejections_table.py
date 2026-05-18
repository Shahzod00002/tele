"""
migrations/add_rejections_table.py
==================================
Миграция: добавить таблицу order_rejections
"""

import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_PATH


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Проверяем, существует ли таблица
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='order_rejections'")
    if cursor.fetchone():
        print("Таблица order_rejections уже существует.")

        # Проверяем, нет ли foreign key constraint
        cursor.execute("PRAGMA foreign_key_list(order_rejections)")
        fks = cursor.fetchall()
        if fks:
            print("Обнаружены внешние ключи. Пересоздаём таблицу без них...")

            # Пересоздаём таблицу без foreign key
            cursor.execute("ALTER TABLE order_rejections RENAME TO order_rejections_old")
            cursor.execute("""
                CREATE TABLE order_rejections (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_number    TEXT NOT NULL,
                    courier_chat_id INTEGER NOT NULL,
                    rejected_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(order_number, courier_chat_id)
                )
            """)
            cursor.execute("""
                INSERT INTO order_rejections (id, order_number, courier_chat_id, rejected_at)
                SELECT id, order_number, courier_chat_id, rejected_at FROM order_rejections_old
            """)
            cursor.execute("DROP TABLE order_rejections_old")

            print("✓ Таблица пересоздана без foreign key")
    else:
        print("Создаём таблицу order_rejections...")
        cursor.execute("""
            CREATE TABLE order_rejections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number    TEXT NOT NULL,
                courier_chat_id INTEGER NOT NULL,
                rejected_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_number, courier_chat_id)
            )
        """)
        print("✓ Таблица создана")

    # Создаём индексы
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_rejections_order ON order_rejections(order_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_rejections_courier ON order_rejections(courier_chat_id)")
    print("✓ Индексы созданы")

    conn.commit()
    conn.close()
    print("Миграция завершена!")


if __name__ == "__main__":
    print("=" * 60)
    print("Миграция: добавление таблицы order_rejections")
    print("=" * 60)
    migrate()