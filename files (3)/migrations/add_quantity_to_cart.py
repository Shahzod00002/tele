"""
migrations/add_quantity_to_cart.py
==================================
Миграция: добавить поле quantity в таблицу cart и объединить дубликаты.
"""

import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_PATH


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Проверяем, есть ли уже поле quantity
    cursor.execute("PRAGMA table_info(cart)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'quantity' not in columns:
        print("Добавляем поле quantity...")
        cursor.execute("ALTER TABLE cart ADD COLUMN quantity INTEGER DEFAULT 1")

        # Объединяем дубликаты
        print("Объединяем дублирующиеся записи...")
        cursor.execute("""
            SELECT user_id, dish_name, price, COUNT(*) as cnt, SUM(price) as total
            FROM cart
            GROUP BY user_id, dish_name
            HAVING COUNT(*) > 1
        """)

        duplicates = cursor.fetchall()
        for dup in duplicates:
            # Удаляем все дубликаты
            cursor.execute(
                "DELETE FROM cart WHERE user_id = ? AND dish_name = ?",
                (dup["user_id"], dup["dish_name"])
            )
            # Вставляем одну запись с quantity
            cursor.execute(
                "INSERT INTO cart (user_id, dish_name, price, quantity) VALUES (?, ?, ?, ?)",
                (dup["user_id"], dup["dish_name"], dup["price"], dup["cnt"])
            )
            print(f"  Объединено: {dup['dish_name']} x{dup['cnt']}")

        conn.commit()
        print("Миграция завершена!")
    else:
        print("Поле quantity уже существует.")

    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Миграция: добавление количества в корзину")
    print("=" * 60)
    migrate()