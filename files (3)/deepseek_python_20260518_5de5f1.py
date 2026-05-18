# check_photo_debug.py
import sqlite3
from config import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Проверяем структуру таблицы menu
c.execute("PRAGMA table_info(menu)")
columns = c.fetchall()
print("Структура таблицы menu:")
for col in columns:
    print(f"  {col['name']}: {col['type']}")

# Проверяем блюда с фото
c.execute("SELECT id, name, photo FROM menu WHERE photo IS NOT NULL AND photo != ''")
dishes = c.fetchall()
print(f"\nНайдено блюд с фото: {len(dishes)}")
for d in dishes:
    print(f"  ID: {d['id']}, Name: {d['name']}, Photo: {d['photo'][:50]}...")

conn.close()