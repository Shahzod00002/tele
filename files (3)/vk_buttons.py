"""
vk_buttons.py
=============
Тексты Reply-кнопок (как в buttons.py из Telegram-версии) + хелперы для
построения клавиатур в формате VK.

VK keyboard — это JSON-структура:
{
  "one_time": false,           # скрыть после нажатия
  "inline":   false,           # инлайн (внутри сообщения) или нижняя
  "buttons":  [[ {...}, ... ], ...]   # массив рядов
}

Каждая кнопка имеет вид:
{
  "action": {
    "type": "text",            # "text" / "callback" / "open_link" / "location" / "open_app"
    "label": "Текст",
    "payload": "{\"cmd\":\"...\"}"   # опционально, JSON-строка ≤ 255 байт
  },
  "color": "primary" / "secondary" / "negative" / "positive"
}

В отличие от Telegram, в VK НЕТ системной кнопки "Поделиться телефоном",
поэтому профиль будет заполняться текстом. Также нет message_handler по
типу "контакт" — найм курьера переделываем на ввод ссылки/ID.
"""
from __future__ import annotations

import json
from typing import Optional


# ════════════════════════════════════════════════════════════════════
#   ТЕКСТЫ КНОПОК — 1-в-1 как в Telegram-версии
# ════════════════════════════════════════════════════════════════════

# ─────────────── Главное меню ─────────────────────────────────────
BTN_VIEW_MENU      = "📋 Смотреть меню"
BTN_FILL_PROFILE   = "📱🏠 Заполнить профиль"
BTN_MY_PROFILE     = "👤 Мой профиль"
BTN_OPEN_CART      = "🛒 Открыть корзину"
BTN_CLEAR_CART     = "🗑 Очистить корзину"
BTN_CHANGE_ADDRESS = "🏠 Сменить адрес"
BTN_CHAT_COURIER   = "📩 Чат с доставщиком"
BTN_SUPPORT        = "💡 Поддержка и помощь"
BTN_SEARCH_DISH    = "🔎 Найти блюдо"
BTN_MY_ORDERS      = "📦 Мои заказы"
BTN_ORDER_HISTORY  = "📜 История заказов"
BTN_CHOOSE_COURIER = "🚴 Выбрать Доставщика"
BTN_ADMIN_PANEL    = "⚙️ Админ-панель"
BTN_BACK           = "<< Назад"

# ─────────────── Меню курьера ─────────────────────────────────────
BTN_COURIER_REPORT = "📊 Мой отчёт"
BTN_UNPAID_ORDERS  = "📋 Неоплаченные заказы"
BTN_MY_PHONE       = "📞 Мой номер для переводов"

# ─────────────── Админ-панель ─────────────────────────────────────
BTN_ADD_DISH           = "🍽️ Добавить блюдо"
BTN_DELETE_DISH        = "❌ Удалить блюдо"
BTN_ADD_PHOTO          = "📸 Добавить фото"
BTN_DELETE_PHOTO       = "🗑 Удалить фото"
BTN_CATEGORIES         = "📁 Категории"
BTN_FREEZE_DISH        = "🥶 Скрыть блюдо"
BTN_UNFREEZE_DISH      = "☀️ Вернуть блюдо"
BTN_FREEZE_ALL         = "🥶 Скрыть всё меню"
BTN_UNFREEZE_ALL       = "☀️ Показать всё меню"
BTN_LIST_FROZEN        = "📜 Список скрытых блюд"
BTN_MSG_COURIERS       = "📩 Написать Доставщикам"
BTN_USERS_DB           = "👥 База пользователей"
BTN_BROADCAST          = "📢 Сделать рассылку"
BTN_ALL_ORDERS         = "📋 Все заказы"
BTN_FIND_CHAT_ID       = "🆔 Найти VK-ID"            # переименовано
BTN_HIRE_COURIER       = "➕ Нанять Доставщика"
BTN_FIRE_COURIER       = "❌ Уволить Доставщика"
BTN_EDIT_COURIER_PHONE = "📱 Изменить номер Доставщика"
BTN_EDIT_PRICES        = "💰 Редактировать цены"
BTN_DISCOUNTS          = "🏷 Скидки"
BTN_ADMIN_REPORT       = "📊 Отчёт по выручке"
BTN_COURIER_LIST       = "📋 Список Доставщиков"

# ─────────────── Экспорт/Импорт меню ──────────────────────────────
BTN_EXPORT_MENU = "📤 Экспорт меню"
BTN_IMPORT_MENU = "📥 Импорт меню"

# ─────────────── Секции админ-панели (только в VK-версии) ─────────
# В Telegram админ-панель имела ~16 рядов кнопок — в VK столько не
# помещается, поэтому делим на 3 раздела.
BTN_ADMIN_MENU_SECTION     = "🍽️ Меню и блюда"
BTN_ADMIN_COURIERS_SECTION = "🚴 Курьеры"
BTN_ADMIN_SERVICE_SECTION  = "🔧 Сервис"
BTN_BACK_TO_ADMIN          = "<< К админ-панели"


# ════════════════════════════════════════════════════════════════════
#   КОНСТАНТЫ VK API
# ════════════════════════════════════════════════════════════════════

# Цвета кнопок в VK (только для Reply-клавиатур, не inline)
COLOR_PRIMARY   = "primary"     # синяя
COLOR_SECONDARY = "secondary"   # белая (дефолт)
COLOR_NEGATIVE  = "negative"    # красная
COLOR_POSITIVE  = "positive"    # зелёная

# Ограничения VK API:
# - Reply-клавиатура: формально до 10 рядов, до 5 кнопок в ряду
# - Inline-клавиатура: до 6 рядов, до 5 кнопок в ряду
# - Длина payload: до 255 байт после json.dumps
# - Длина label: до 40 символов
#
# ВАЖНО: на практике VK отдаёт ошибку 911 "buttons contain too much rows"
# уже на 8–9 рядах, особенно в мобильном клиенте. Безопасный предел —
# 6–7 рядов в reply-клавиатуре. Поэтому объёмные меню (главное меню,
# админ-панель) разбиваем по 2 кнопки в ряд и/или на подменю.
MAX_LABEL_LEN   = 40
MAX_PAYLOAD_LEN = 255
SAFE_ROWS_REPLY = 7         # практический потолок для надёжной работы


# ════════════════════════════════════════════════════════════════════
#   БИЛДЕРЫ КЛАВИАТУР
# ════════════════════════════════════════════════════════════════════

class Keyboard:
    """
    Builder для VK keyboard. Используется как:

        kb = Keyboard(one_time=False)
        kb.row(text_button("📋 Меню"), text_button("🛒 Корзина"))
        kb.row(text_button("Назад", color=COLOR_NEGATIVE))
        json_str = kb.dump()    # → строка для параметра keyboard в messages.send

    Inline-клавиатура (внутри сообщения, аналог TG inline) — `inline=True`.
    """

    def __init__(self, one_time: bool = False, inline: bool = False):
        self._rows: list[list[dict]] = []
        self._one_time = one_time
        self._inline = inline

    def row(self, *buttons: dict) -> "Keyboard":
        """Добавить ряд кнопок. Если в ряду больше 5 — VK отклонит сообщение."""
        if not buttons:
            return self
        if len(buttons) > 5:
            raise ValueError(f"В ряду не более 5 кнопок, получено {len(buttons)}")
        self._rows.append(list(buttons))
        return self

    def empty(self) -> bool:
        return not self._rows

    def to_dict(self) -> dict:
        # Inline-клавиатура НЕ может быть one_time — это ограничение VK
        if self._inline:
            return {"inline": True, "buttons": self._rows}
        return {
            "one_time": self._one_time,
            "inline":   False,
            "buttons":  self._rows,
        }

    def dump(self) -> str:
        """JSON-строка для параметра keyboard в messages.send.

        Если рядов больше безопасного потолка, печатает предупреждение в
        stderr — VK может вернуть ошибку 911 на больших клавиатурах.
        """
        rows = len(self._rows)
        if self._inline and rows > 6:
            import sys
            print(f"[vk_buttons] WARN: inline-клавиатура {rows} рядов "
                  f"(лимит 6), будет ошибка VK 911", file=sys.stderr)
        elif not self._inline and rows > SAFE_ROWS_REPLY:
            import sys
            print(f"[vk_buttons] WARN: reply-клавиатура {rows} рядов "
                  f"(безопасный потолок {SAFE_ROWS_REPLY}), "
                  f"возможна ошибка VK 911", file=sys.stderr)
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ─── Конструкторы отдельных кнопок ────────────────────────────────────

def text_button(label: str, color: str = COLOR_SECONDARY,
                payload: Optional[dict] = None) -> dict:
    """Обычная текстовая кнопка. При нажатии бот получит обычное сообщение
    с этим label в text. Если задан payload — придёт также в message.payload
    (строкой JSON)."""
    if len(label) > MAX_LABEL_LEN:
        # Не падаем, но обрезаем, чтобы клавиатуру не отверг VK.
        label = label[:MAX_LABEL_LEN]
    btn = {
        "action": {"type": "text", "label": label},
        "color":  color,
    }
    if payload is not None:
        payload_str = json.dumps(payload, ensure_ascii=False)
        if len(payload_str.encode("utf-8")) > MAX_PAYLOAD_LEN:
            raise ValueError(f"Payload длиннее {MAX_PAYLOAD_LEN} байт: {payload_str}")
        btn["action"]["payload"] = payload_str
    return btn


def callback_button(label: str, payload: dict,
                    color: str = COLOR_PRIMARY) -> dict:
    """
    Callback-кнопка (аналог Inline-кнопки Telegram с callback_data).
    Работает ТОЛЬКО в inline-клавиатуре. При нажатии генерирует
    событие message_event, которое можно обработать без перезагрузки
    сообщения и ответить через messages.sendMessageEventAnswer.
    """
    payload_str = json.dumps(payload, ensure_ascii=False)
    if len(payload_str.encode("utf-8")) > MAX_PAYLOAD_LEN:
        raise ValueError(f"Payload длиннее {MAX_PAYLOAD_LEN} байт: {payload_str}")
    if len(label) > MAX_LABEL_LEN:
        label = label[:MAX_LABEL_LEN]
    return {
        "action": {
            "type":    "callback",
            "label":   label,
            "payload": payload_str,
        },
        "color": color,
    }


def link_button(label: str, url: str) -> dict:
    """Кнопка-ссылка. Работает только в inline-клавиатуре."""
    if len(label) > MAX_LABEL_LEN:
        label = label[:MAX_LABEL_LEN]
    return {
        "action": {
            "type":  "open_link",
            "label": label,
            "link":  url,
        },
    }


# ─── Утилита: «пустая» клавиатура — снимает любые кнопки у пользователя ─

EMPTY_KEYBOARD = json.dumps({"buttons": [], "one_time": True}, ensure_ascii=False)