"""
db.py
=====
Слой работы с БД. Все обращения к SQLite — через функции этого модуля.
"""

from __future__ import annotations
import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional

from config import DB_PATH
from crypto_utils import encrypt_optional, decrypt_optional

logger = logging.getLogger(__name__)


def create_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def conn_ctx():
    conn = create_connection()
    try:
        yield conn
    finally:
        conn.close()


# ─────────────────────────── Инициализация ──────────────────────────

def init_schema() -> None:
    """Создать схему и подкатить миграции на старых БД."""
    with conn_ctx() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                phone       TEXT,
                address     TEXT,
                preferred_courier_id INTEGER,
                consent_given_at     DATETIME,
                consent_version      TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL UNIQUE,
                sort_order INTEGER DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name        TEXT NOT NULL,
                price       REAL NOT NULL,
                frozen      INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS cart (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                dish_name  TEXT NOT NULL,
                price      REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                order_number TEXT,
                total_price  REAL,
                status       TEXT DEFAULT 'waiting',
                payment_method TEXT,
                message_id   INTEGER,
                courier_id   INTEGER,
                courier_msg_id INTEGER,
                assigned_at  DATETIME,
                attempts     INTEGER DEFAULT 0,
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                delivered_at DATETIME
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS couriers (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT UNIQUE,
                telegram_chat_id  INTEGER UNIQUE,
                payment_phone     TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS action_log (
                user_id   INTEGER,
                action    TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS consents_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                consent_version TEXT NOT NULL,
                action          TEXT NOT NULL,
                timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS support_threads (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id    TEXT NOT NULL,
                user_id      INTEGER NOT NULL,
                topic        TEXT,
                order_number TEXT,
                author       TEXT NOT NULL,
                text         TEXT NOT NULL,
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS discounts (
                menu_id     INTEGER PRIMARY KEY,
                kind        TEXT NOT NULL,
                value       REAL NOT NULL,
                valid_until DATETIME,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (menu_id) REFERENCES menu(id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                courier_id   INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                stars        INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("PRAGMA table_info(cart)")
        columns = [col[1] for col in c.fetchall()]

        if 'quantity' not in columns:
            c.execute("ALTER TABLE cart ADD COLUMN quantity INTEGER DEFAULT 1")
            logger.info("Миграция: добавлено поле quantity в таблицу cart")

        # Создаём уникальный индекс для предотвращения дублей (user_id, dish_name)
        c.execute("""
                   CREATE INDEX IF NOT EXISTS idx_cart_user_dish 
                   ON cart(user_id, dish_name)
               """)
        # Замените создание таблицы order_rejections на это:
        c.execute("""
            CREATE TABLE IF NOT EXISTS order_rejections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number    TEXT NOT NULL,
                courier_chat_id INTEGER NOT NULL,
                rejected_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_number, courier_chat_id)
            )
        """)

        # Создаём индекс для ускорения поиска
        c.execute("CREATE INDEX IF NOT EXISTS idx_order_rejections_order ON order_rejections(order_number)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_order_rejections_courier ON order_rejections(courier_chat_id)")
        # ─── миграции старых БД ───
        def add_col(table, column, ddl):
            c.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in c.fetchall()}
            if column not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
                logger.info("Миграция: %s.%s", table, column)

        add_col("users", "name",                 "name TEXT")
        add_col("users", "preferred_courier_id", "preferred_courier_id INTEGER")
        add_col("users", "consent_given_at",     "consent_given_at DATETIME")
        add_col("users", "consent_version",      "consent_version TEXT")
        add_col("menu",  "frozen",               "frozen INTEGER NOT NULL DEFAULT 0")
        add_col("orders","message_id",           "message_id INTEGER")
        add_col("orders","courier_id",           "courier_id INTEGER")
        add_col("orders","courier_msg_id",       "courier_msg_id INTEGER")
        add_col("orders","assigned_at",          "assigned_at DATETIME")
        add_col("orders","attempts",             "attempts INTEGER DEFAULT 0")
        add_col("orders","delivered_at",         "delivered_at DATETIME")
        add_col("orders","payment_method",       "payment_method TEXT")
        add_col("couriers","payment_phone",      "payment_phone TEXT")
        add_col("orders","paid",                 "paid INTEGER DEFAULT 0")
        add_col("orders","comment",              "comment TEXT")
        add_col("menu", "category_id", "category_id INTEGER")
        add_col("menu", "photo", "photo TEXT")  # Добавить в список миграций

        # Создать таблицу категорий если её нет
        c.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL UNIQUE,
                sort_order INTEGER DEFAULT 0
            )
        """)

        # Добавить категорию по умолчанию если таблица пуста
        c.execute("SELECT COUNT(*) FROM categories")
        if c.fetchone()[0] == 0:
            default_categories = [
                (1, 'Завтрак'), (2, 'Обед'), (3, 'Напитки'),
                (4, 'Шаурма'), (5, 'Шашлыки'), (6, 'Салат'),
                (7, 'Блюда'), (8, 'Булочки')
            ]
            for cat_id, cat_name in default_categories:
                c.execute("INSERT OR IGNORE INTO categories (id, name, sort_order) VALUES (?, ?, ?)",
                          (cat_id, cat_name, cat_id))
            # Обновить существующие блюда — привязать к категории "Блюда" (id=7)
            c.execute("UPDATE menu SET category_id = 7 WHERE category_id IS NULL")
        conn.commit()
    logger.info("Схема БД инициализирована")


# ─────────────────────── ПДн пользователя ──────────────────────────

def save_user_pii(user_id, *, name=None, phone=None, address=None):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT name, phone, address FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        old_n = row["name"]    if row else None
        old_p = row["phone"]   if row else None
        old_a = row["address"] if row else None
        new_n = encrypt_optional(name)    if name    is not None else old_n
        new_p = encrypt_optional(phone)   if phone   is not None else old_p
        new_a = encrypt_optional(address) if address is not None else old_a
        c.execute("""
            INSERT INTO users (id, name, phone, address)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, phone = excluded.phone, address = excluded.address
        """, (user_id, new_n, new_p, new_a))
        conn.commit()


def get_user_pii(user_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT name, phone, address FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
    if not row:
        return {"name": None, "phone": None, "address": None}
    return {
        "name":    decrypt_optional(row["name"]),
        "phone":   decrypt_optional(row["phone"]),
        "address": decrypt_optional(row["address"]),
    }


def update_user_address(user_id, address):
    save_user_pii(user_id, address=address)


def get_user_contact_info(user_id):
    pii = get_user_pii(user_id)
    return pii["phone"], pii["address"]


# ──────────────────────────── Согласия ─────────────────────────────

def has_valid_consent(user_id, current_version):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT consent_version, consent_given_at FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
    if not row or not row["consent_given_at"]:
        return False
    return row["consent_version"] == current_version


def record_consent(user_id, version, action="accepted"):
    with conn_ctx() as conn:
        c = conn.cursor()
        if action == "accepted":
            c.execute("""
                INSERT INTO users (id, consent_given_at, consent_version)
                VALUES (?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(id) DO UPDATE SET
                    consent_given_at = CURRENT_TIMESTAMP,
                    consent_version  = excluded.consent_version
            """, (user_id, version))
        c.execute("INSERT INTO consents_log (user_id, consent_version, action) VALUES (?, ?, ?)",
                  (user_id, version, action))
        conn.commit()


def revoke_user_data(user_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""UPDATE users SET name=NULL, phone=NULL, address=NULL,
                     consent_given_at=NULL, consent_version=NULL WHERE id = ?""", (user_id,))
        c.execute("INSERT INTO consents_log (user_id, consent_version, action) VALUES (?, '', 'revoked')",
                  (user_id,))
        conn.commit()


def delete_user_completely(user_id):
    """
    Полное удаление пользователя.

    В разных версиях БД могут существовать FK на users.id (исторически
    они могли быть созданы вручную или другой версией скрипта). Чтобы
    операция была идемпотентной и не падала с FOREIGN KEY constraint:
      1) временно отключаем PRAGMA foreign_keys для этого соединения;
      2) явно зачищаем все таблицы, где есть user_id;
      3) удаляем из users;
      4) пишем в consents_log запись 'deleted' (для аудита по 152-ФЗ).

    Заказы и тикеты поддержки СОХРАНЯЕМ как историю — открытых ПДн
    в них нет (имя/телефон/адрес лежат только в users и шифруются).
    Если в orders есть user_id, обнуляем его — заказ остаётся, владелец
    обезличивается.
    """
    with conn_ctx() as conn:
        c = conn.cursor()
        # 1) Снимаем FK на время транзакции
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            # 2) Чистим связанные данные
            #    - корзина: удалить
            c.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
            #    - рейтинги, выставленные этим пользователем: удалить
            c.execute("DELETE FROM ratings WHERE user_id = ?", (user_id,))
            #    - тикеты поддержки от этого пользователя: удалить
            c.execute("DELETE FROM support_threads WHERE user_id = ?", (user_id,))
            #    - заказы: обезличиваем, не удаляем (нужны для отчётности)
            c.execute("UPDATE orders SET user_id = NULL WHERE user_id = ?", (user_id,))
            #    - если кто-то выбрал этого юзера как «своего курьера» — обнуляем
            c.execute(
                "UPDATE users SET preferred_courier_id = NULL WHERE preferred_courier_id = ?",
                (user_id,),
            )
            #    - старые consents_log этого пользователя оставляем как есть
            #      (журнал согласий нужен для аудита)
            #    - action_log оставляем — там user_id, но это аудит-лог

            # 3) Сам пользователь
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))
            rowcount = c.rowcount

            # 4) Запись в журнал согласий — ПОСЛЕ удаления, FK уже не мешает
            c.execute(
                "INSERT INTO consents_log (user_id, consent_version, action) "
                "VALUES (?, '', 'deleted')",
                (user_id,),
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            # 5) Восстанавливаем FK для следующих операций на этом соединении
            #    (контекстный менеджер закроет соединение, но на всякий случай)
            try:
                c.execute("PRAGMA foreign_keys = ON")
            except Exception:
                pass

        return rowcount


def get_user_for_admin(user_id):
    """
    Получить расшифрованные ПДн одного пользователя для админ-карточки.
    Возвращает dict с id/name/phone/address или None, если пользователя нет.
    """
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, phone, address FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
    if not row:
        return None
    try:
        name = decrypt_optional(row["name"]) if row["name"] else None
    except Exception:
        name = "[ошибка]"
    try:
        phone = decrypt_optional(row["phone"]) if row["phone"] else None
    except Exception:
        phone = "[ошибка]"
    try:
        address = decrypt_optional(row["address"]) if row["address"] else None
    except Exception:
        address = "[ошибка]"
    return {
        "id": row["id"],
        "name": name,
        "phone": phone,
        "address": address,
    }


def user_exists(user_id) -> bool:
    """Есть ли запись пользователя в таблице users?"""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1", (user_id,))
        return c.fetchone() is not None


# ─────────────────────────── Логи действий ─────────────────────────

def log_user_action(user_id, action):
    with conn_ctx() as conn:
        conn.execute("INSERT INTO action_log (user_id, action) VALUES (?, ?)", (user_id, action))
        conn.commit()


def get_recent_actions(limit=20):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM action_log ORDER BY timestamp DESC LIMIT ?", (limit,))
        return c.fetchall()


# ─────────────────────────────── Меню ──────────────────────────────

# ─────────────────────────────── Категории ────────────────────────────

def get_categories():
    """Получить все категории."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM categories ORDER BY sort_order, id")
        return c.fetchall()


def add_category(name):
    """Добавить категорию."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM categories")
        next_order = c.fetchone()[0]
        c.execute("INSERT INTO categories (name, sort_order) VALUES (?, ?)", (name, next_order))
        conn.commit()
        return c.lastrowid


def delete_category(category_id):
    """Удалить категорию и все блюда в ней."""
    with conn_ctx() as conn:
        c = conn.cursor()
        # Удаляем блюда этой категории
        c.execute("DELETE FROM menu WHERE category_id = ?", (category_id,))
        # Удаляем категорию
        c.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        return c.rowcount


def get_category_name(category_id):
    """Получить название категории."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
        row = c.fetchone()
        return row["name"] if row else "Без категории"


# ─────────────────────────────── Меню ──────────────────────────────

def get_menu_items_available(category_id=None):
    """Получить доступные блюда, опционально по категории."""
    with conn_ctx() as conn:
        c = conn.cursor()
        if category_id:
            c.execute("SELECT id, name, price FROM menu WHERE frozen = 0 AND category_id = ? ORDER BY name",
                     (category_id,))
        else:
            c.execute("SELECT id, name, price FROM menu WHERE frozen = 0 ORDER BY name")
        return c.fetchall()


def get_menu_items_frozen(category_id=None):
    """Получить скрытые блюда."""
    with conn_ctx() as conn:
        c = conn.cursor()
        if category_id:
            c.execute("SELECT id, name, price FROM menu WHERE frozen = 1 AND category_id = ? ORDER BY name",
                     (category_id,))
        else:
            c.execute("SELECT id, name, price FROM menu WHERE frozen = 1 ORDER BY name")
        return c.fetchall()


# Добавить после функций работы с меню:

def set_dish_photo(menu_id: int, photo_file_id: str) -> bool:
    """Сохранить file_id фото для блюда."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("UPDATE menu SET photo = ? WHERE id = ?", (photo_file_id, menu_id))
        conn.commit()
        return c.rowcount > 0


def get_dish_photo(menu_id: int) -> Optional[str]:
    """Получить file_id фото блюда."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT photo FROM menu WHERE id = ?", (menu_id,))
        row = c.fetchone()
        return row["photo"] if row else None


def get_menu_item_by_id(menu_id: int):
    """Получить блюдо по ID (включая фото)."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT id, category_id, name, price, frozen, photo FROM menu WHERE id = ?", (menu_id,))
        row = c.fetchone()
        if row:
            # Преобразуем Row в словарь для удобства
            return dict(row)
        return None


def search_menu(query, category_id=None):
    """Поиск блюд."""
    with conn_ctx() as conn:
        c = conn.cursor()
        if category_id:
            c.execute("SELECT id, name, price FROM menu WHERE name LIKE ? AND frozen = 0 AND category_id = ?",
                     (f"%{query}%", category_id))
        else:
            c.execute("SELECT id, name, price FROM menu WHERE name LIKE ? AND frozen = 0",
                     (f"%{query}%",))
        return c.fetchall()


def add_menu_item(name, price, category_id=None):
    """Добавить блюдо."""
    with conn_ctx() as conn:
        conn.execute("INSERT INTO menu (name, price, category_id) VALUES (?, ?, ?)",
                    (name, price, category_id))
        conn.commit()


def delete_menu_item(name, category_id=None):
    """Удалить блюдо."""
    with conn_ctx() as conn:
        c = conn.cursor()
        if category_id:
            c.execute("DELETE FROM menu WHERE name = ? AND category_id = ?", (name, category_id))
        else:
            c.execute("DELETE FROM menu WHERE name = ?", (name,))
        conn.commit()
        return c.rowcount


def set_dish_frozen_by_id(menu_id, frozen):
    """Заморозить/разморозить блюдо."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM menu WHERE id = ?", (menu_id,))
        row = c.fetchone()
        if not row:
            return None
        c.execute("UPDATE menu SET frozen = ? WHERE id = ?",
                 (1 if frozen else 0, menu_id))
        conn.commit()
        return row["name"]


def set_all_dishes_frozen(frozen, category_id=None):
    """Заморозить/разморозить все блюда."""
    with conn_ctx() as conn:
        c = conn.cursor()
        target = 1 if frozen else 0
        if category_id:
            c.execute("UPDATE menu SET frozen = ? WHERE frozen != ? AND category_id = ?",
                     (target, target, category_id))
        else:
            c.execute("UPDATE menu SET frozen = ? WHERE frozen != ?", (target, target))
        conn.commit()
        return c.rowcount


def update_dish_price(dish_id, new_price):
    """Обновить цену блюда."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM menu WHERE id = ?", (dish_id,))
        row = c.fetchone()
        if not row:
            return None
        c.execute("UPDATE menu SET price = ? WHERE id = ?", (new_price, dish_id))
        conn.commit()
        return row["name"]


def get_menu_with_discounts(category_id=None):
    """Получить меню со скидками."""
    with conn_ctx() as conn:
        c = conn.cursor()
        if category_id:
            c.execute("""
                SELECT m.id, m.name, m.price, m.frozen 
                FROM menu m 
                WHERE m.frozen = 0 AND m.category_id = ?
                ORDER BY m.name
            """, (category_id,))
        else:
            c.execute("""
                SELECT m.id, m.name, m.price, m.frozen 
                FROM menu m 
                WHERE m.frozen = 0 
                ORDER BY m.name
            """)
        items = c.fetchall()

    result = []
    for it in items:
        d = get_discount(it["id"])
        final = apply_discount(it["price"], d)
        result.append({
            "id": it["id"],
            "name": it["name"],
            "original_price": it["price"],
            "final_price": final,
            "discount": d,
        })
    return result


# ─────────────────────────── Скидки ────────────────────────────────

def set_discount(menu_id, kind, value, valid_until=None):
    if kind not in ("percent", "rub"):
        raise ValueError(f"Unknown discount kind: {kind}")
    with conn_ctx() as conn:
        conn.execute("""
            INSERT INTO discounts (menu_id, kind, value, valid_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(menu_id) DO UPDATE SET
                kind = excluded.kind, value = excluded.value,
                valid_until = excluded.valid_until,
                created_at = CURRENT_TIMESTAMP
        """, (menu_id, kind, value, valid_until))
        conn.commit()


def remove_discount(menu_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM discounts WHERE menu_id = ?", (menu_id,))
        conn.commit()
        return c.rowcount > 0


def get_discount(menu_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT kind, value, valid_until FROM discounts
            WHERE menu_id = ?
              AND (valid_until IS NULL OR valid_until > CURRENT_TIMESTAMP)
        """, (menu_id,))
        return c.fetchone()


def get_all_discounts():
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT d.menu_id, d.kind, d.value, d.valid_until, m.name, m.price
            FROM discounts d JOIN menu m ON m.id = d.menu_id
            WHERE d.valid_until IS NULL OR d.valid_until > CURRENT_TIMESTAMP
            ORDER BY m.name
        """)
        return c.fetchall()


def apply_discount(price, discount):
    if not discount:
        return price
    if discount["kind"] == "percent":
        result = price * (1 - discount["value"] / 100)
    else:
        result = price - discount["value"]
    return max(0.0, round(result, 2))



# ─────────────────────────── Корзина ───────────────────────────────

# Заменить существующие функции на эти:

def add_to_cart(user_id: int, dish_name: str, price: float, quantity: int = 1) -> None:
    """
    Добавить блюдо в корзину с указанным количеством.
    Если блюдо уже есть - увеличиваем количество.
    """
    with conn_ctx() as conn:
        c = conn.cursor()

        # Проверяем, есть ли уже такое блюдо в корзине
        c.execute(
            "SELECT id, quantity FROM cart WHERE user_id = ? AND dish_name = ?",
            (user_id, dish_name)
        )
        existing = c.fetchone()

        if existing:
            # Обновляем количество
            new_quantity = existing["quantity"] + quantity
            c.execute(
                "UPDATE cart SET quantity = ?, price = ? WHERE id = ?",
                (new_quantity, price, existing["id"])
            )
        else:
            # Добавляем новое
            c.execute(
                "INSERT INTO cart (user_id, dish_name, price, quantity) VALUES (?, ?, ?, ?)",
                (user_id, dish_name, price, quantity)
            )

        conn.commit()
    log_user_action(user_id, f"added_to_cart:{dish_name} x{quantity}")


def remove_from_cart(user_id: int, dish_name: str, quantity: int = None) -> None:
    """
    Удалить блюдо из корзины или уменьшить количество.

    Args:
        user_id: ID пользователя
        dish_name: Название блюда
        quantity: Количество для удаления (None = удалить всё)
    """
    with conn_ctx() as conn:
        c = conn.cursor()

        if quantity is None:
            # Удаляем полностью
            c.execute(
                "DELETE FROM cart WHERE user_id = ? AND dish_name = ?",
                (user_id, dish_name)
            )
        else:
            # Уменьшаем количество
            c.execute(
                "SELECT id, quantity FROM cart WHERE user_id = ? AND dish_name = ?",
                (user_id, dish_name)
            )
            existing = c.fetchone()

            if existing:
                new_quantity = existing["quantity"] - quantity
                if new_quantity <= 0:
                    c.execute(
                        "DELETE FROM cart WHERE user_id = ? AND dish_name = ?",
                        (user_id, dish_name)
                    )
                else:
                    c.execute(
                        "UPDATE cart SET quantity = ? WHERE id = ?",
                        (new_quantity, existing["id"])
                    )

        conn.commit()


def update_cart_quantity(user_id: int, dish_name: str, quantity: int) -> None:
    """Установить точное количество блюда в корзине."""
    if quantity <= 0:
        remove_from_cart(user_id, dish_name)
        return

    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO cart (user_id, dish_name, price, quantity) 
               VALUES (?, ?, (SELECT price FROM cart WHERE user_id = ? AND dish_name = ?), ?)
               ON CONFLICT DO UPDATE SET quantity = ?""",
            (user_id, dish_name, user_id, dish_name, quantity, quantity)
        )
        conn.commit()


def get_cart(user_id: int):
    """Получить корзину с группировкой по блюдам."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT dish_name, price, quantity, (price * quantity) as total
            FROM cart 
            WHERE user_id = ? 
            ORDER BY dish_name
        """, (user_id,))
        return c.fetchall()


def get_cart_items_count(user_id: int) -> int:
    """Получить общее количество позиций в корзине (с учётом quantity)."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT SUM(quantity) as total FROM cart WHERE user_id = ?",
            (user_id,)
        )
        row = c.fetchone()
        return row["total"] if row and row["total"] else 0

def get_cart_total(user_id: int) -> float:
    """Получить общую сумму корзины с учётом количества."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT SUM(price * quantity) as total FROM cart WHERE user_id = ?",
            (user_id,)
        )
        row = c.fetchone()
        return float(row["total"]) if row and row["total"] else 0.0

def clear_cart(user_id: int) -> None:
    """Очистить всю корзину."""
    with conn_ctx() as conn:
        conn.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
        conn.commit()


# ─────────────────────────── Заказы ────────────────────────────────

def create_order(user_id: int, order_number: str, total_price: float, payment_method: str, courier_id: int, comment: str = None):
    with conn_ctx() as conn:
        conn.execute("""
            INSERT INTO orders (user_id, order_number, total_price, payment_method,
                                courier_id, assigned_at, attempts, comment, status)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1, ?, 'waiting')
        """, (user_id, order_number, total_price, payment_method, courier_id, comment))
        conn.commit()


def set_order_message_id(order_number, message_id):
    with conn_ctx() as conn:
        conn.execute("UPDATE orders SET message_id = ? WHERE order_number = ?",
                     (message_id, order_number))
        conn.commit()


def set_courier_message_id(order_number, message_id):
    with conn_ctx() as conn:
        conn.execute("UPDATE orders SET courier_msg_id = ? WHERE order_number = ?",
                     (message_id, order_number))
        conn.commit()


def get_order(order_number):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE order_number = ?", (order_number,))
        return c.fetchone()


def update_order_status(order_number, status):
    with conn_ctx() as conn:
        c = conn.cursor()
        if status == "Доставлено":
            c.execute("""UPDATE orders SET status = ?, delivered_at = CURRENT_TIMESTAMP
                         WHERE order_number = ?""", (status, order_number))
        else:
            c.execute("UPDATE orders SET status = ? WHERE order_number = ?",
                      (status, order_number))
        c.execute("SELECT message_id FROM orders WHERE order_number = ?", (order_number,))
        row = c.fetchone()
        conn.commit()
        return row["message_id"] if row and row["message_id"] else None


def reassign_order(order_number, new_courier_id):
    with conn_ctx() as conn:
        conn.execute("""
            UPDATE orders SET courier_id = ?,
                              assigned_at = CURRENT_TIMESTAMP,
                              attempts = attempts + 1,
                              status = 'waiting',
                              courier_msg_id = NULL
            WHERE order_number = ?
        """, (new_courier_id, order_number))
        conn.commit()


def get_user_orders(user_id, limit=10):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""SELECT * FROM orders WHERE user_id = ?
                     ORDER BY created_at DESC LIMIT ?""", (user_id, limit))
        return c.fetchall()


def get_user_active_orders(user_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""SELECT order_number, status, created_at FROM orders
                     WHERE user_id = ? AND status NOT IN ('Доставлено', 'Отклонено')
                     ORDER BY created_at DESC LIMIT 10""", (user_id,))
        return c.fetchall()


def get_user_id_by_order_number(order_number):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM orders WHERE order_number = ?", (order_number,))
        row = c.fetchone()
        return row["user_id"] if row else None


def get_all_orders():
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT o.* FROM orders o ORDER BY o.created_at DESC")
        return c.fetchall()


# ─────────────────────────── Курьеры ───────────────────────────────

def get_all_couriers():
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM couriers")
        return c.fetchall()


def get_couriers_by_rating():
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.id, c.name, c.telegram_chat_id, c.payment_phone,
                   COALESCE(AVG(r.stars), 0) AS avg_rating,
                   COUNT(r.id) AS ratings_count
            FROM couriers c
            LEFT JOIN ratings r ON r.courier_id = c.telegram_chat_id
            GROUP BY c.id
            ORDER BY avg_rating DESC, ratings_count DESC, c.name
        """)
        return c.fetchall()


def get_courier_by_chat_id(chat_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM couriers WHERE telegram_chat_id = ?", (chat_id,))
        return c.fetchone()


def add_courier(name, chat_id, payment_phone=None):
    with conn_ctx() as conn:
        c = conn.cursor()
        # Проверяем, существует ли уже курьер с таким chat_id
        c.execute("SELECT id, payment_phone FROM couriers WHERE telegram_chat_id = ?", (chat_id,))
        row = c.fetchone()
        if row:
            # Обновляем существующего
            new_phone = payment_phone if payment_phone else row["payment_phone"]
            c.execute("""
                UPDATE couriers SET name = ?, payment_phone = ?
                WHERE telegram_chat_id = ?
            """, (name, new_phone, chat_id))
        else:
            # Создаём нового
            c.execute("""
                INSERT INTO couriers (name, telegram_chat_id, payment_phone)
                VALUES (?, ?, ?)
            """, (name, chat_id, payment_phone))
        conn.commit()


def update_courier_payment_phone(chat_id, payment_phone):
    with conn_ctx() as conn:
        conn.execute("UPDATE couriers SET payment_phone = ? WHERE telegram_chat_id = ?",
                     (payment_phone, chat_id))
        conn.commit()


def delete_courier_by_name(name):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM couriers WHERE name = ?", (name,))
        conn.commit()
        return c.rowcount


def get_user_preferred_courier(user_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT preferred_courier_id FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        return row["preferred_courier_id"] if row and row["preferred_courier_id"] else None


def set_user_preferred_courier(user_id, courier_chat_id):
    with conn_ctx() as conn:
        conn.execute("""
            INSERT INTO users (id, preferred_courier_id) VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET preferred_courier_id = excluded.preferred_courier_id
        """, (user_id, courier_chat_id))
        conn.commit()


def next_courier_for_reassign(exclude_chat_ids: list) -> Optional[int]:
    """Лучший по рейтингу курьер, не входящий в exclude."""
    try:
        if not exclude_chat_ids:
            with conn_ctx() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT c.telegram_chat_id,
                           COALESCE(AVG(r.stars), 0) AS avg_rating
                    FROM couriers c
                    LEFT JOIN ratings r ON r.courier_id = c.telegram_chat_id
                    GROUP BY c.id
                    ORDER BY avg_rating DESC, c.id
                    LIMIT 1
                """)
                row = c.fetchone()
                return row["telegram_chat_id"] if row else None
        else:
            placeholders = ",".join("?" * len(exclude_chat_ids))
            with conn_ctx() as conn:
                c = conn.cursor()
                c.execute(f"""
                    SELECT c.telegram_chat_id,
                           COALESCE(AVG(r.stars), 0) AS avg_rating
                    FROM couriers c
                    LEFT JOIN ratings r ON r.courier_id = c.telegram_chat_id
                    WHERE c.telegram_chat_id NOT IN ({placeholders})
                    GROUP BY c.id
                    ORDER BY avg_rating DESC, c.id
                    LIMIT 1
                """, exclude_chat_ids)
                row = c.fetchone()
                return row["telegram_chat_id"] if row else None
    except Exception as e:
        logger.error(f"Ошибка поиска следующего курьера: {e}")
        return None


def get_all_courier_chat_ids() -> list:
    """Получить список chat_id всех курьеров."""
    try:
        with conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT telegram_chat_id FROM couriers")
            return [r["telegram_chat_id"] for r in c.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка получения списка курьеров: {e}")
        return []

# ─────────────────────────── Рейтинг ───────────────────────────────

def save_rating(order_number, courier_id, user_id, stars):
    if not (1 <= stars <= 5):
        return False
    try:
        with conn_ctx() as conn:
            conn.execute("""
                INSERT INTO ratings (order_number, courier_id, user_id, stars)
                VALUES (?, ?, ?, ?)
            """, (order_number, courier_id, user_id, stars))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_courier_rating(courier_chat_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(AVG(stars), 0) AS avg, COUNT(*) AS cnt
            FROM ratings WHERE courier_id = ?
        """, (courier_chat_id,))
        row = c.fetchone()
    return {"avg": float(row["avg"]), "count": int(row["cnt"])}


# ─────────────────── Тикеты поддержки (треды) ──────────────────────

def create_support_thread(thread_id, user_id, topic, order_number, text):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO support_threads
                (thread_id, user_id, topic, order_number, author, text)
            VALUES (?, ?, ?, ?, 'user', ?)
        """, (thread_id, user_id, topic, order_number, text))
        conn.commit()
        return c.lastrowid


def add_support_message(thread_id, author, text):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""SELECT user_id, topic, order_number FROM support_threads
                     WHERE thread_id = ? ORDER BY id LIMIT 1""", (thread_id,))
        row = c.fetchone()
        if not row:
            raise ValueError(f"Тред {thread_id} не найден")
        c.execute("""
            INSERT INTO support_threads
                (thread_id, user_id, topic, order_number, author, text)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (thread_id, row["user_id"], row["topic"], row["order_number"],
              author, text))
        conn.commit()


def get_thread_meta(thread_id):
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""SELECT user_id, topic, order_number FROM support_threads
                     WHERE thread_id = ? ORDER BY id LIMIT 1""", (thread_id,))
        return c.fetchone()

def save_support_ticket(user_id, topic, order_number, text):
    """Создать тикет поддержки (обёртка для обратной совместимости)."""
    import uuid
    thread_id = f"ticket_{uuid.uuid4().hex[:12]}"
    return create_support_thread(thread_id, user_id, topic, order_number, text)

def get_order_courier(order_number):
    """Получить chat_id курьера по номеру заказа."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT courier_id FROM orders WHERE order_number = ?", (order_number,))
        row = c.fetchone()
        return row["courier_id"] if row else None
# ─────────────────── Пользователи (для админа) ─────────────────────

def get_all_user_ids():
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM users")
        return [r["id"] for r in c.fetchall()]


def get_all_users_for_admin():
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, phone, address FROM users")
        rows = c.fetchall()

    result = []
    for r in rows:
        try:
            name = decrypt_optional(r["name"]) if r["name"] else "—"
        except Exception:
            name = "[ошибка]"
        try:
            phone = decrypt_optional(r["phone"]) if r["phone"] else "—"
        except Exception:
            phone = "[ошибка]"
        try:
            address = decrypt_optional(r["address"]) if r["address"] else "—"
        except Exception:
            address = "[ошибка]"

        result.append({
            "id": r["id"],
            "name": name,
            "phone": phone,
            "address": address,
        })
    return result

def mark_order_paid(order_number, paid=True):
    """Отметить заказ как оплаченный или неоплаченный."""
    with conn_ctx() as conn:
        conn.execute("UPDATE orders SET paid = ? WHERE order_number = ?",
                     (1 if paid else 0, order_number))
        conn.commit()


def get_unpaid_orders_for_courier(courier_chat_id):
    """Получить неоплаченные заказы курьера."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT order_number, user_id, total_price, payment_method, 
                   delivered_at, paid
            FROM orders 
            WHERE courier_id = ? 
              AND status = 'Доставлено' 
              AND (paid = 0 OR paid IS NULL)
            ORDER BY delivered_at DESC
        """, (courier_chat_id,))
        return c.fetchall()
# ───────────────────────────── Отчёты ──────────────────────────────

def _date_where(date_from, date_to, prefix=""):
    where, params = [], []
    if date_from:
        where.append(f"DATE({prefix}delivered_at) >= DATE(?)")
        params.append(date_from)
    if date_to:
        where.append(f"DATE({prefix}delivered_at) <= DATE(?)")
        params.append(date_to)
    return where, params


def courier_stats(courier_chat_id, date_from=None, date_to=None):
    we, pe = _date_where(date_from, date_to)
    where = ["courier_id = ?", "status = 'Доставлено'"] + we
    params = [courier_chat_id] + pe
    wsql = " AND ".join(where)
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(total_price), 0) AS total,
                   COALESCE(SUM(CASE WHEN payment_method = 'Перевод 💳' THEN total_price ELSE 0 END), 0) AS by_card,
                   COALESCE(SUM(CASE WHEN payment_method = 'Наличными 💵' THEN total_price ELSE 0 END), 0) AS by_cash
            FROM orders WHERE {wsql}
        """, params)
        row = c.fetchone()
    return {
        "count":   int(row["cnt"]),
        "total":   float(row["total"]),
        "by_card": float(row["by_card"]),
        "by_cash": float(row["by_cash"]),
    }


def courier_orders(courier_chat_id, date_from=None, date_to=None):
    we, pe = _date_where(date_from, date_to)
    where = ["courier_id = ?", "status = 'Доставлено'"] + we
    params = [courier_chat_id] + pe
    wsql = " AND ".join(where)
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT order_number, total_price, payment_method, delivered_at, user_id
            FROM orders WHERE {wsql}
            ORDER BY delivered_at DESC
        """, params)
        return c.fetchall()


def admin_stats(date_from=None, date_to=None):
    we, pe = _date_where(date_from, date_to)
    where = ["status = 'Доставлено'"] + we
    wsql = " AND ".join(where)
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(total_price), 0) AS total,
                   COALESCE(SUM(CASE WHEN payment_method = 'Перевод 💳' THEN total_price ELSE 0 END), 0) AS by_card,
                   COALESCE(SUM(CASE WHEN payment_method = 'Наличными 💵' THEN total_price ELSE 0 END), 0) AS by_cash
            FROM orders WHERE {wsql}
        """, pe)
        row = c.fetchone()
        totals = {
            "count":   int(row["cnt"]),
            "total":   float(row["total"]),
            "by_card": float(row["by_card"]),
            "by_cash": float(row["by_cash"]),
        }
        c.execute(f"""
            SELECT o.courier_id,
                   c.name AS courier_name,
                   COUNT(*) AS cnt,
                   COALESCE(SUM(o.total_price), 0) AS total,
                   COALESCE(SUM(CASE WHEN o.payment_method = 'Перевод 💳' THEN o.total_price ELSE 0 END), 0) AS by_card,
                   COALESCE(SUM(CASE WHEN o.payment_method = 'Наличными 💵' THEN o.total_price ELSE 0 END), 0) AS by_cash
            FROM orders o
            LEFT JOIN couriers c ON c.telegram_chat_id = o.courier_id
            WHERE {wsql.replace('status', 'o.status')}
            GROUP BY o.courier_id
            ORDER BY total DESC
        """, pe)
        couriers = [dict(r) for r in c.fetchall()]
    return {"totals": totals, "couriers": couriers}


def all_delivered_orders(date_from=None, date_to=None):
    we, pe = _date_where(date_from, date_to, prefix="o.")
    where = ["o.status = 'Доставлено'"] + we
    wsql = " AND ".join(where)
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT o.order_number, o.total_price, o.payment_method,
                   o.delivered_at, o.user_id, o.courier_id,
                   c.name AS courier_name
            FROM orders o
            LEFT JOIN couriers c ON c.telegram_chat_id = o.courier_id
            WHERE {wsql}
            ORDER BY o.delivered_at DESC
        """, pe)
        return c.fetchall()


# ─────────────────── Экспорт/Импорт меню ──────────────────────────

def export_menu_to_dict() -> dict:
    """Экспортирует всё меню (категории + блюда + фото) в словарь для JSON."""
    with conn_ctx() as conn:
        c = conn.cursor()

        c.execute("SELECT id, name, sort_order FROM categories ORDER BY sort_order, id")
        categories = c.fetchall()

        result = {
            "version": "1.0",
            "categories": []
        }

        for cat in categories:
            c.execute("""
                SELECT id, name, price, frozen, photo 
                FROM menu 
                WHERE category_id = ? 
                ORDER BY name
            """, (cat["id"],))
            dishes = c.fetchall()

            cat_data = {
                "name": cat["name"],
                "sort_order": cat["sort_order"],
                "dishes": [
                    {
                        "name": dish["name"],
                        "price": dish["price"],
                        "frozen": bool(dish["frozen"]),
                        "photo": dish["photo"]  # Сохраняем file_id фото
                    }
                    for dish in dishes
                ]
            }
            result["categories"].append(cat_data)

    return result


def import_menu_from_dict(data: dict, clear_existing: bool = True) -> dict:
    """Импортирует меню из словаря (включая фото)."""
    stats = {
        "categories_created": 0,
        "categories_updated": 0,
        "dishes_created": 0,
        "dishes_updated": 0,
        "errors": []
    }

    with conn_ctx() as conn:
        c = conn.cursor()

        if clear_existing:
            c.execute("DELETE FROM menu")
            c.execute("DELETE FROM categories")
            conn.commit()

        for cat_data in data.get("categories", []):
            cat_name = cat_data.get("name", "").strip()
            if not cat_name:
                stats["errors"].append("Пропущена категория без имени")
                continue

            sort_order = cat_data.get("sort_order", 0)

            c.execute("SELECT id FROM categories WHERE name = ?", (cat_name,))
            existing = c.fetchone()

            if existing:
                c.execute("UPDATE categories SET sort_order = ? WHERE name = ?", (sort_order, cat_name))
                stats["categories_updated"] += 1
                cat_id = existing["id"]
            else:
                c.execute("INSERT INTO categories (name, sort_order) VALUES (?, ?)", (cat_name, sort_order))
                cat_id = c.lastrowid
                stats["categories_created"] += 1

            for dish_data in cat_data.get("dishes", []):
                dish_name = dish_data.get("name", "").strip()
                if not dish_name:
                    stats["errors"].append(f"Пропущено блюдо без имени в категории {cat_name}")
                    continue

                price = dish_data.get("price", 0)
                frozen = 1 if dish_data.get("frozen", False) else 0
                photo = dish_data.get("photo")  # Получаем file_id фото

                c.execute("SELECT id FROM menu WHERE name = ? AND category_id = ?", (dish_name, cat_id))
                existing_dish = c.fetchone()

                if existing_dish:
                    c.execute("UPDATE menu SET price = ?, frozen = ?, photo = ? WHERE id = ?",
                              (price, frozen, photo, existing_dish["id"]))
                    stats["dishes_updated"] += 1
                else:
                    c.execute("INSERT INTO menu (name, price, frozen, category_id, photo) VALUES (?, ?, ?, ?, ?)",
                              (dish_name, price, frozen, cat_id, photo))
                    stats["dishes_created"] += 1

        conn.commit()

    return stats


# Добавить в конец раздела с курьерами в db.py

def update_courier_phone(chat_id: int, payment_phone: str) -> bool:
    """
    Обновить номер телефона для переводов у курьера.

    Args:
        chat_id: Telegram chat_id курьера
        payment_phone: Новый номер телефона

    Returns:
        bool: True если обновление успешно, False если курьер не найден
    """
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE couriers 
            SET payment_phone = ? 
            WHERE telegram_chat_id = ?
        """, (payment_phone, chat_id))
        conn.commit()
        return c.rowcount > 0


def get_courier_phone(chat_id: int) -> Optional[str]:
    """Получить номер телефона курьера для переводов."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT payment_phone FROM couriers WHERE telegram_chat_id = ?", (chat_id,))
        row = c.fetchone()
        return row["payment_phone"] if row else None


def get_all_couriers_with_phones() -> list:
    """Получить всех курьеров с их номерами телефонов."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, name, telegram_chat_id, payment_phone 
            FROM couriers 
            ORDER BY name
        """)
        return c.fetchall()

def get_cart_summary(user_id: int) -> dict:
    """Получить сводку по корзине."""
    with conn_ctx() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) as item_count, 
                   SUM(quantity) as total_quantity,
                   SUM(price * quantity) as total_price
            FROM cart 
            WHERE user_id = ?
        """, (user_id,))
        row = c.fetchone()
        return {
            "item_count": row["item_count"] or 0,
            "total_quantity": row["total_quantity"] or 0,
            "total_price": float(row["total_price"] or 0)
        }

def add_rejected_courier(order_number: str, courier_chat_id: int) -> None:
    """Добавить курьера в список отказавшихся от заказа."""
    try:
        with conn_ctx() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO order_rejections (order_number, courier_chat_id, rejected_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (order_number, courier_chat_id))
            conn.commit()
            logger.info(f"Курьер {courier_chat_id} добавлен в отказники заказа {order_number}")
    except Exception as e:
        logger.error(f"Ошибка добавления курьера в отказники: {e}")


def get_rejected_couriers(order_number: str) -> list:
    """Получить список курьеров, отказавшихся от заказа."""
    try:
        with conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT courier_chat_id FROM order_rejections WHERE order_number = ?", (order_number,))
            return [row["courier_chat_id"] for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка получения списка отказавшихся курьеров: {e}")
        return []


def clear_rejected_couriers(order_number: str) -> None:
    """Очистить список отказавшихся курьеров (при повторном заказе)."""
    try:
        with conn_ctx() as conn:
            conn.execute("DELETE FROM order_rejections WHERE order_number = ?", (order_number,))
            conn.commit()
            logger.info(f"Очищен список отказников для заказа {order_number}")
    except Exception as e:
        logger.error(f"Ошибка очистки списка отказников: {e}")