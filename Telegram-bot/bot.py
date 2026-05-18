"""
bot.py
======
Главный модуль бота. Только хэндлеры — вся работа с БД делегирована в db.py,
шифрование — в crypto_utils.py.

Что нового по сравнению с предыдущей версией:
* токен и admin_chat_id из env;
* ПДн шифруются при записи и расшифровываются при чтении;
* перед первым сбором ПДн запрашивается согласие (152-ФЗ);
* кнопки переименованы согласно ТЗ;
* поддержка — через Telegram Mini App, без текстовых диалогов;
* логирование действий — только в БД, без ПДн;
* убраны дубли функций и захардкоженные пути.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time  # ← ДОБАВИТЬ ЭТОТ ИМПОРТ
from pathlib import Path  # ← ДОБАВИТЬ ЭТОТ ИМПОРТ
from datetime import datetime, timedelta
from math import ceil
from typing import Optional
from openpyxl import Workbook       # ← для Excel-отчётов
from utils import temporary_file, temporary_directory, cleanup_all_temp_files
import telebot
from telebot import types
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from docx import Document

import config
import db
import buttons as B

# ───────────────────────────── Логирование ───────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

# ───────────────────────────── Бот ───────────────────────────────────
bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode=None)

# ─────────────────────── In-memory состояния ─────────────────────────
# Эти структуры — рабочая память на время сеанса. Не для долгого хранения!
user_payments: dict[int, str] = {}     # user_id -> метод оплаты
admin_state:   dict[int, object] = {}  # user_id -> произвольное состояние
admin_edit_state: dict[int, dict] = {} # для редактирования цен
admin_broadcast_state: dict[int, str] = {}
user_last_messages: dict[int, dict] = {}
discount_state: dict[int, dict] = {}            # промежуточный ввод скидки
report_state: dict[int, dict] = {}              # ожидание дат для произвольного периода
support_state: dict[int, dict] = {}             # user_id -> состояние при создании тикета
support_reply_state: dict[int, dict] = {}       # admin_id -> {user_id, thread_id} (ждём ответ админа)
support_continue_state: dict[int, str] = {}     # user_id -> thread_id (юзер пишет дальше)
user_threads: dict[int, str] = {}               # user_id -> thread_id
hire_state: dict[int, dict] = {}              # временные данные при найме курьера
ORDER_TIMEOUT_SEC = 5*60                      # 5 минут

# Пагинация
ITEMS_PER_PAGE = 10
DISHES_PER_PAGE = 12
ORDERS_PER_PAGE = 5

# ───────────────────────── Утилиты ───────────────────────────────────

# Добавить после определения bot, перед остальными функциями

# ───────────────────────── Утилиты для безопасной отправки ─────────────────────────

def safe_send_message(chat_id: int, text: str, parse_mode: str = None,
                      reply_markup=None, disable_web_page_preview: bool = False,
                      **kwargs) -> bool:
    """
    Безопасно отправляет сообщение, обрабатывая ошибки форматирования.
    Если возникает ошибка с парсингом, отправляет без форматирования.

    Returns:
        bool: True если сообщение отправлено, False при ошибке
    """
    try:
        if parse_mode:
            bot.send_message(
                chat_id, text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
                **kwargs
            )
        else:
            bot.send_message(
                chat_id, text,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
                **kwargs
            )
        return True
    except Exception as e:
        error_msg = str(e)
        if "can't parse entities" in error_msg:
            # Отправляем без форматирования
            try:
                bot.send_message(
                    chat_id, text,
                    parse_mode=None,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview,
                    **kwargs
                )
                return True
            except Exception as e2:
                logger.error(f"Ошибка отправки сообщения (без форматирования): {e2}")
                return False
        else:
            logger.error(f"Ошибка отправки сообщения: {e}")
            return False


def safe_edit_message_text(chat_id: int, message_id: int, text: str,
                           parse_mode: str = None, reply_markup=None) -> bool:
    """
    Безопасно редактирует текст сообщения.
    Если сообщение не содержит текст (фото, видео и т.д.), отправляет новое.
    """
    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        error_msg = str(e)
        if "there is no text" in error_msg or "message to edit" in error_msg:
            # Отправляем новое сообщение
            try:
                bot.send_message(
                    chat_id,
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                # Пытаемся удалить старое
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
                return True
            except Exception as e2:
                logger.error(f"Ошибка отправки нового сообщения: {e2}")
                return False
        elif "can't parse entities" in error_msg:
            # Пробуем без форматирования
            try:
                bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode=None,
                    reply_markup=reply_markup
                )
                return True
            except Exception as e2:
                logger.error(f"Ошибка редактирования без форматирования: {e2}")
                return False
        else:
            logger.error(f"Ошибка редактирования сообщения: {e}")
            return False
def fmt_money(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", " ")

def fmt_discount(d):
    if not d:
        return ""
    if d["kind"] == "percent":
        return f"(-{d['value']}%)"
    return f"(-{d['value']} ₽)"
def fmt_rating(avg: float, count: int) -> str:
    if count == 0:
        return "—"
    stars = "⭐" * round(avg)
    return f"{stars} {avg:.1f} ({count})"

def is_courier(chat_id: int) -> bool:
    """Проверка, является ли пользователь курьером"""
    courier = db.get_courier_by_chat_id(chat_id)
    return courier is not None
def is_admin(chat_id: int) -> bool:
    return chat_id == config.ADMIN_CHAT_ID


def generate_order_number() -> str:
    return datetime.now().strftime("%d%m%Y-%H%M%S")


# ───────────────────── Главное меню / админ-панель ───────────────────

def send_main_menu(chat_id: int, greeting: bool = False) -> None:
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(B.BTN_VIEW_MENU))
    markup.add(KeyboardButton(B.BTN_SEARCH_DISH))
    markup.add(
        KeyboardButton(B.BTN_FILL_PROFILE),
        KeyboardButton(B.BTN_MY_PROFILE),
    )
    markup.add(
        KeyboardButton(B.BTN_OPEN_CART),
        KeyboardButton(B.BTN_CLEAR_CART),
    )
    markup.add(
        KeyboardButton(B.BTN_CHANGE_ADDRESS),
    )
    markup.add(
        KeyboardButton(B.BTN_CHOOSE_COURIER),
        KeyboardButton(B.BTN_CHAT_COURIER),
    )
    markup.add(
        KeyboardButton(B.BTN_MY_ORDERS),
        KeyboardButton(B.BTN_ORDER_HISTORY),
    )

    # Кнопка-WebApp для поддержки. Если URL не задан — оставляем обычной
    # кнопкой, чтобы бот не падал при старте.

    markup.add(KeyboardButton(B.BTN_SUPPORT))

    if is_courier(chat_id):
        markup.add(
            KeyboardButton(B.BTN_COURIER_REPORT),
            KeyboardButton(B.BTN_UNPAID_ORDERS),
            KeyboardButton(B.BTN_MY_PHONE),  # ← Новая кнопка для курьера
        )

    if is_admin(chat_id):
        markup.add(KeyboardButton(B.BTN_ADMIN_PANEL))

    text = "Добро пожаловать! Выберите действие:" if greeting else "Главное меню:"
    bot.send_message(chat_id, text, reply_markup=markup)


def send_admin_panel(chat_id: int) -> None:
    if not is_admin(chat_id):
        bot.send_message(chat_id, "У вас нет доступа к админ-командам.")
        return
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(B.BTN_ADD_DISH), KeyboardButton(B.BTN_DELETE_DISH))
    markup.add(KeyboardButton(B.BTN_ADD_PHOTO), KeyboardButton(B.BTN_DELETE_PHOTO))  # ← Добавить
    markup.add(KeyboardButton(B.BTN_FREEZE_DISH), KeyboardButton(B.BTN_UNFREEZE_DISH))
    markup.add(KeyboardButton(B.BTN_FREEZE_ALL),  KeyboardButton(B.BTN_UNFREEZE_ALL))
    markup.add(KeyboardButton(B.BTN_LIST_FROZEN), KeyboardButton(B.BTN_EDIT_PRICES))
    markup.add(KeyboardButton(B.BTN_CATEGORIES), KeyboardButton(B.BTN_DISCOUNTS))
    markup.add(KeyboardButton(B.BTN_HIRE_COURIER), KeyboardButton(B.BTN_FIRE_COURIER))
    markup.add(KeyboardButton(B.BTN_MSG_COURIERS), KeyboardButton(B.BTN_FIND_CHAT_ID))
    markup.add(KeyboardButton(B.BTN_USERS_DB),     KeyboardButton(B.BTN_ALL_ORDERS))
    markup.add(KeyboardButton(B.BTN_ADMIN_REPORT))
    markup.add(KeyboardButton(B.BTN_BROADCAST))
    # ⬇️ НОВЫЕ КНОПКИ ⬇️
    markup.add(KeyboardButton(B.BTN_EXPORT_MENU), KeyboardButton(B.BTN_IMPORT_MENU))
    markup.add(KeyboardButton(B.BTN_EDIT_COURIER_PHONE), KeyboardButton(B.BTN_COURIER_LIST))  # ← Новая кнопка
    # ⬆️ НОВЫЕ КНОПКИ ⬆️
    markup.add(KeyboardButton(B.BTN_BACK))
    bot.send_message(chat_id, "⚙️ Админ-панель:", reply_markup=markup)


# ───────────────────────── /start ────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    send_main_menu(message.chat.id, greeting=True)


@bot.message_handler(func=lambda m: m.text == B.BTN_BACK)
def go_back(message):
    send_main_menu(message.chat.id)


@bot.message_handler(func=lambda m: m.text == B.BTN_ADMIN_PANEL)
def open_admin_panel(message):
    send_admin_panel(message.chat.id)


# ════════════════════════════════════════════════════════════════════
#  Блок 3: Согласие на обработку ПДн (152-ФЗ)
# ════════════════════════════════════════════════════════════════════

def request_consent(chat_id: int) -> None:
    """Показать пользователю экран согласия."""
    text = (
        "🔒 *Согласие на обработку персональных данных*\n\n"
        "Прежде чем мы продолжим, нам необходимо ваше согласие на обработку "
        "персональных данных (ФИО, телефон, адрес) в соответствии с "
        "Федеральным законом № 152-ФЗ.\n\n"
        f"📄 [Политика конфиденциальности]({config.PRIVACY_POLICY_URL})\n\n"
        f"Версия документа: {config.CONSENT_VERSION}"
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("✅ Принимаю условия", callback_data="consent_accept"),
        InlineKeyboardButton("❌ Отказываюсь",      callback_data="consent_decline"),
    )
    bot.send_message(chat_id, text, parse_mode="Markdown",
                     reply_markup=markup, disable_web_page_preview=True)


@bot.callback_query_handler(func=lambda c: c.data in ("consent_accept", "consent_decline"))
def handle_consent(call):
    user_id = call.message.chat.id
    if call.data == "consent_accept":
        db.record_consent(user_id, config.CONSENT_VERSION, "accepted")
        db.log_user_action(user_id, "consent_accepted")
        bot.edit_message_text(
            "✅ Спасибо! Согласие зафиксировано. Теперь можно заполнить профиль.",
            chat_id=user_id, message_id=call.message.message_id,
        )
        # Сразу запускаем сбор контакта
        ask_for_contact(user_id)
    else:
        db.record_consent(user_id, config.CONSENT_VERSION, "declined")
        db.log_user_action(user_id, "consent_declined")
        bot.edit_message_text(
            "❌ Вы отказались от обработки ПДн.\n\n"
            "Вы можете смотреть меню, но оформление заказа недоступно — "
            "для доставки нам нужны адрес и телефон.",
            chat_id=user_id, message_id=call.message.message_id,
        )


def require_consent(user_id: int) -> bool:
    """
    Шлюз: возвращает True, если согласие есть. Иначе сам показывает
    экран согласия и возвращает False — вызывающий код просто делает return.
    """
    if db.has_valid_consent(user_id, config.CONSENT_VERSION):
        return True
    request_consent(user_id)
    return False


# ════════════════════════════════════════════════════════════════════
#  Профиль: телефон + адрес + ФИО (с шифрованием!)
# ════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == B.BTN_FILL_PROFILE)
def start_profile(message):
    user_id = message.chat.id

    # Для админа не требуется согласие, но показываем специальное сообщение
    if is_admin(user_id):
        ask_for_admin_contact(user_id)
        return

    # Для обычных пользователей
    if not require_consent(user_id):
        return
    ask_for_contact(user_id)


def ask_for_admin_contact(chat_id: int) -> None:
    """Запрос контакта для админа с пояснением."""
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(KeyboardButton("📱 Отправить контакт", request_contact=True))
    markup.add(KeyboardButton("<< Назад"))
    bot.send_message(
        chat_id,
        "📞 *Введите номер телефона:*\n\n"
        "Просто напишите его в чат, например: `+71234567890`\n\n"
        "Или нажмите кнопку «Отправить контакт» (но помните, что это для найма Доставщика!)",
        parse_mode="Markdown",
        reply_markup=markup
    )


def ask_for_contact(chat_id: int) -> None:
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(KeyboardButton("📱 Отправить контакт", request_contact=True))
    bot.send_message(chat_id, "Поделитесь номером телефона:", reply_markup=markup)


@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    """Обработка отправленного контакта."""
    user_id = message.chat.id

    # Проверяем, находимся ли мы в режиме добавления номера для курьера
    state = admin_state.get(user_id, {})

    # Если админ и в режиме редактирования номера курьера
    if is_admin(user_id) and state.get("action") == "edit_courier_phone":
        handle_contact_for_courier_phone(message)
        return

    # Если админ и в режиме добавления номера при найме
    if is_admin(user_id) and state.get("action") == "add_courier_phone":
        handle_contact_for_courier_phone(message)
        return

    # Если админ и в режиме найма курьера (обычный найм)
    if is_admin(user_id) and state.get("action") != "edit_courier_phone":
        # Это найм курьера
        admin_hire_courier_contact(message)
        return

    # Для обычных пользователей - заполнение профиля
    if not require_consent(user_id):
        return

    if not message.contact:
        bot.send_message(user_id, "⚠️ Не удалось получить контакт. Попробуйте снова.")
        return

    phone = message.contact.phone_number
    bot.send_message(user_id, "Спасибо! Теперь введите ваш 🏠 адрес:")
    bot.register_next_step_handler(message, _profile_step_address, phone)


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.text and m.text.strip().startswith('+') and len(m.text.strip()) >= 10)
def admin_text_phone_handler(message):
    """Обработка текстового ввода номера телефона админом для своего профиля."""
    user_id = message.chat.id

    # Проверяем, не находимся ли мы в режиме редактирования курьера
    state = admin_state.get(user_id, {})
    if state.get("action") in ("edit_courier_phone", "add_courier_phone"):
        # Это режим редактирования курьера - пропускаем
        return

    # Это заполнение профиля админа
    phone = message.text.strip()

    # Валидация номера
    import re
    digits = re.sub(r'\D', '', phone)
    if len(digits) < 10 or len(digits) > 15:
        bot.send_message(user_id, "⚠️ Неверный формат номера. Номер должен содержать 10-15 цифр.")
        return

    # Приводим к формату с +
    if not phone.startswith('+'):
        phone = '+' + digits

    # Сохраняем в профиль (шифруется автоматически)
    db.save_user_pii(user_id, phone=phone)
    db.log_user_action(user_id, f"profile_phone_updated: {phone[-4:]}")  # Логируем только последние 4 цифры

    # Проверяем, есть ли уже имя и адрес
    pii = db.get_user_pii(user_id)

    if not pii["name"] or not pii["address"]:
        # Если нет имени, запрашиваем
        if not pii["name"]:
            bot.send_message(user_id, "✅ Номер телефона сохранён!\n\nТеперь введите ваше ФИО:")
            bot.register_next_step_handler(message, _admin_profile_step_name, phone)
        elif not pii["address"]:
            bot.send_message(user_id, "✅ Номер телефона сохранён!\n\nТеперь введите ваш адрес:")
            bot.register_next_step_handler(message, _admin_profile_step_address, phone)
    else:
        # Профиль полностью заполнен
        bot.send_message(
            user_id,
            f"✅ Номер телефона обновлён: `{phone}`\n\nВаш профиль полностью заполнен!",
            parse_mode="Markdown"
        )
        send_main_menu(user_id)


def _admin_profile_step_name(message, phone):
    """Шаг заполнения имени для админа."""
    name = (message.text or "").strip()
    if not name:
        bot.send_message(message.chat.id, "⚠️ ФИО не может быть пустым. Попробуйте ещё раз.")
        return

    db.save_user_pii(message.chat.id, name=name)

    # Запрашиваем адрес
    bot.send_message(message.chat.id, "✅ ФИО сохранено!\n\nТеперь введите ваш адрес:")
    bot.register_next_step_handler(message, _admin_profile_step_address, phone)


def _admin_profile_step_address(message, phone):
    """Шаг заполнения адреса для админа."""
    address = (message.text or "").strip()
    if not address:
        bot.send_message(message.chat.id, "⚠️ Адрес не может быть пустым. Попробуйте ещё раз.")
        return

    db.save_user_pii(message.chat.id, address=address)
    db.log_user_action(message.chat.id, "admin_profile_filled")

    bot.send_message(
        message.chat.id,
        f"✅ Профиль администратора полностью заполнен!\n\n"
        f"📞 Телефон: `{phone}`\n"
        f"👤 ФИО: {os.name}\n"
        f"🏠 Адрес: {address}",
        parse_mode="Markdown"
    )
    send_main_menu(message.chat.id)


def _profile_step_address(message, phone):
    address = (message.text or "").strip()
    if not address:
        bot.send_message(message.chat.id, "⚠️ Адрес не может быть пустым. Попробуйте ещё раз.")
        return
    bot.send_message(message.chat.id, "👤 Введите ФИО (Фамилия Имя Отчество):")
    bot.register_next_step_handler(message, _profile_step_name, phone, address)


def _profile_step_name(message, phone, address):
    name = (message.text or "").strip()
    if not name:
        bot.send_message(message.chat.id, "⚠️ ФИО не может быть пустым. Попробуйте ещё раз.")
        return
    user_id = message.chat.id
    # save_user_pii зашифрует поля внутри
    db.save_user_pii(user_id, name=name, phone=phone, address=address)
    db.log_user_action(user_id, "profile_filled")
    bot.send_message(user_id, f"Спасибо, {name}! Профиль сохранён. Откройте «{B.BTN_VIEW_MENU}», чтобы заказать.")
    send_main_menu(user_id)


# ─── Смена только адреса ────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_CHANGE_ADDRESS)
def change_address_start(message):
    if not require_consent(message.chat.id):
        return
    bot.send_message(message.chat.id, "Введите новый 🏠 адрес:")
    bot.register_next_step_handler(message, _save_new_address)


def _save_new_address(message):
    address = (message.text or "").strip()
    if not address:
        bot.send_message(message.chat.id, "⚠️ Адрес не может быть пустым.")
        return
    db.update_user_address(message.chat.id, address)
    db.log_user_action(message.chat.id, "address_updated")
    bot.send_message(message.chat.id, "✅ Адрес обновлён.")


# ════════════════════════════════════════════════════════════════════
#  Меню (просмотр и пагинация)
# ════════════════════════════════════════════════════════════════════

def generate_menu_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    items = db.get_menu_with_discounts()
    total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    markup = InlineKeyboardMarkup(row_width=1)
    start, end = page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE

    for it in items[start:end]:
        if it["discount"]:
            label = (f"{it['name']} — {fmt_money(it['original_price'])} → "
                     f"{fmt_money(it['final_price'])} ₽")
        else:
            label = f"{it['name']} — {fmt_money(it['final_price'])} ₽"
        markup.add(InlineKeyboardButton(label, callback_data=f"add_to_cart|{it['id']}"))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⏪", callback_data="page:0"))
        nav.append(InlineKeyboardButton("◀", callback_data=f"page:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"page:{page+1}"))
        nav.append(InlineKeyboardButton("⏩", callback_data=f"page:{total_pages-1}"))
    if nav:
        markup.row(*nav)
    markup.add(InlineKeyboardButton("Закрыть", callback_data="close_menu"))
    return markup


@bot.message_handler(func=lambda m: m.text == B.BTN_VIEW_MENU)
def show_menu(message):
    categories = db.get_categories()
    if not categories:
        bot.send_message(message.chat.id, "📋 Меню пока пусто.")
        return

    # Создаем клавиатуру
    markup = InlineKeyboardMarkup()

    # Добавляем кнопки по две в ряд
    row_buttons = []
    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"{cat['name']}",
            callback_data=f"show_cat|{cat['id']}|0",
        ))
        # Каждые 2 кнопки добавляем в новый ряд
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    # Добавляем кнопку закрытия отдельно
    markup.row(InlineKeyboardButton("❌Закрыть", callback_data="close_menu"))

    bot.send_message(message.chat.id, "📋 *Меню*\n\nВыберите категорию:", parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("show_cat|"))
def show_category_dishes(call):
    _, category_id, page = call.data.split("|")
    category_id = int(category_id)
    page = int(page)

    category_name = db.get_category_name(category_id)
    items = db.get_menu_with_discounts(category_id)

    if not items:
        bot.answer_callback_query(call.id, "В этой категории пока нет блюд", show_alert=True)
        return

    total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start, end = page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE

    markup = InlineKeyboardMarkup(row_width=1)

    for it in items[start:end]:
        if it["discount"]:
            label = (f"{it['name']} — {fmt_money(it['original_price'])} → "
                     f"{fmt_money(it['final_price'])} ₽")
        else:
            label = f"{it['name']} — {fmt_money(it['final_price'])} ₽"

        # Получаем блюдо с фото
        dish = db.get_menu_item_by_id(it["id"])

        # Проверяем наличие фото (работает и с Row, и с dict)
        has_photo = False
        if dish:
            if isinstance(dish, dict):
                has_photo = dish.get("photo") is not None
            else:
                # Для sqlite3.Row
                try:
                    has_photo = dish["photo"] is not None
                except (KeyError, IndexError):
                    has_photo = False

        if has_photo:
            markup.row(
                InlineKeyboardButton(f"📸 {label}", callback_data=f"show_photo|{it['id']}|{category_id}|{page}")
            )
        else:
            markup.add(InlineKeyboardButton(label, callback_data=f"add_to_cart|{it['id']}"))

    # Навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⏪", callback_data=f"show_cat|{category_id}|0"))
        nav.append(InlineKeyboardButton("◀", callback_data=f"show_cat|{category_id}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"show_cat|{category_id}|{page + 1}"))
        nav.append(InlineKeyboardButton("⏩", callback_data=f"show_cat|{category_id}|{total_pages - 1}"))
    if len(nav) > 1:
        markup.row(*nav)
    markup.add(InlineKeyboardButton("<< К категориям", callback_data="back_to_categories"))

    # Отправляем или редактируем сообщение
    try:
        bot.edit_message_text(
            f"📋 *{category_name}*",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup,
        )
    except Exception as e:
        if "there is no text" in str(e):
            bot.send_message(
                call.message.chat.id,
                f"📋 *{category_name}*",
                parse_mode="Markdown",
                reply_markup=markup,
            )
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
        else:
            logger.error(f"Ошибка в show_category_dishes: {e}")

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "back_to_categories")
def back_to_categories(call):
    categories = db.get_categories()
    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"{cat['name']}",
            callback_data=f"show_cat|{cat['id']}|0",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    markup.row(InlineKeyboardButton("❌Закрыть", callback_data="close_menu"))

    # Используем безопасное редактирование
    safe_edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="📋 *Меню*\n\nВыберите категорию:",
        parse_mode="Markdown",
        reply_markup=markup
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("show_photo|"))
def cb_show_photo(call):
    """Показать фото блюда с кнопками."""
    _, menu_id, category_id, page = call.data.split("|")
    menu_id = int(menu_id)
    category_id = int(category_id)
    page = int(page)

    dish = db.get_menu_item_by_id(menu_id)
    if not dish or not dish["photo"]:
        bot.answer_callback_query(call.id, "Фото не найдено", show_alert=True)
        return

    # Получаем актуальную цену со скидкой
    discount = db.get_discount(menu_id)
    final_price = db.apply_discount(dish["price"], discount)

    # Экранируем спецсимволы в названии блюда
    import re
    def escape_markdown(text):
        """Экранирует спецсимволы для Markdown."""
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

    safe_name = escape_markdown(dish["name"])

    # Формируем подпись без использования Markdown форматирования
    # Или используем HTML вместо Markdown (надёжнее)
    if discount:
        # Вариант 1: без форматирования
        caption = f"{dish['name']}\n{dish['price']} ₽ → {final_price} ₽"

        # Вариант 2: с HTML (раскомментировать если нужно)
        # caption = f"<b>{dish['name']}</b>\n<s>{dish['price']} ₽</s> → <b>{final_price} ₽</b>"
        # parse_mode = "HTML"
    else:
        caption = f"{dish['name']}\n{final_price} ₽"

    # Кнопки
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕🛒В корзину", callback_data=f"add_to_cart|{menu_id}"),
        InlineKeyboardButton("<< К списку", callback_data=f"show_cat|{category_id}|{page}")
    )

    try:
        # Удаляем старое сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

        # Отправляем фото с обычным текстом (без Markdown)
        bot.send_photo(
            call.message.chat.id,
            dish["photo"],
            caption=caption,
            parse_mode=None,  # Отключаем Markdown
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        # Если не удалось отправить фото, отправляем текст
        bot.send_message(
            call.message.chat.id,
            f"{caption}\n\nФото временно недоступно",
            reply_markup=markup
        )

    bot.answer_callback_query(call.id)
# Добавить вспомогательную функцию для безопасного получения значения
def safe_get(row, key, default=None):
    """Безопасно получить значение из sqlite3.Row или dict."""
    if row is None:
        return default
    try:
        # Если это dict
        if isinstance(row, dict):
            return row.get(key, default)
        # Если это sqlite3.Row
        return row[key] if key in row.keys() else default
    except (KeyError, IndexError, TypeError):
        return default
def safe_edit_message_text(chat_id: int, message_id: int, text: str,
                          parse_mode: str = None, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасно редактирует текст сообщения.
    Если сообщение не содержит текст (фото, видео и т.д.), отправляет новое.
    Возвращает True если успешно, False если пришлось отправить новое.
    """
    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        error_msg = str(e)
        if "there is no text" in error_msg or "message to edit" in error_msg:
            # Отправляем новое сообщение
            bot.send_message(
                chat_id,
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            # Пытаемся удалить старое
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            return False
        else:
            raise e


@bot.callback_query_handler(func=lambda c: c.data == "close_menu")
def close_menu_callback(call):
    """Закрыть меню."""
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        # Если не удалось удалить, пытаемся отредактировать
        if "message can't be deleted" in str(e):
            safe_edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="✅ Меню закрыто",
                reply_markup=None
            )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("page:"))
def handle_menu_pagination(call):
    if call.data == "none":
        bot.answer_callback_query(call.id)
        return
    if call.data == "close_menu":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return
    page = int(call.data.split(":")[1])

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=generate_menu_keyboard(page),
        )
    except Exception as e:
        if "there is no text" in str(e):
            # Если сообщение не имеет текста, отправляем новое
            text, markup = render_cart(call.message.chat.id)
            bot.send_message(
                call.message.chat.id,
                text,
                parse_mode="Markdown",
                reply_markup=markup
            )
        else:
            raise e

    bot.answer_callback_query(call.id)


# ─── Добавление в корзину ───────────────────────────────────────────
# Формат callback_data: add_to_cart|menu_id — цена со скидкой считается
# на момент клика, чтобы скидки применялись актуально.

@bot.callback_query_handler(func=lambda c: c.data.startswith("add_to_cart|"))
def cb_add_to_cart(call):
    try:
        _, menu_id = call.data.split("|", 1)
        menu_id = int(menu_id)
    except:
        bot.answer_callback_query(call.id, "Ошибка данных", show_alert=True)
        return

    item = db.get_menu_item_by_id(menu_id)
    if not item or item["frozen"]:
        bot.answer_callback_query(call.id, "Блюдо недоступно", show_alert=True)
        return

    # Запись в cart защищена FK на users(id) в части БД, унаследованных
    # от старой схемы. Если пользователь удалил профиль или ни разу не
    # давал согласия — записи в users ещё/уже нет, и INSERT упадёт.
    # Мягко предлагаем заполнить профиль.
    if not db.user_exists(call.message.chat.id):
        bot.answer_callback_query(
            call.id,
            "Сначала примите соглашение и заполните профиль "
            f"(«{B.BTN_FILL_PROFILE}»).",
            show_alert=True,
        )
        # Дополнительно сразу показываем экран согласия, если его нет
        try:
            require_consent(call.message.chat.id)
        except Exception:
            pass
        return

    discount = db.get_discount(menu_id)
    final_price = db.apply_discount(item["price"], discount)

    # Добавляем с количеством 1
    db.add_to_cart(call.message.chat.id, item["name"], final_price, 1)

    # Получаем текущее количество в корзине
    items = db.get_cart(call.message.chat.id)
    current_item = next((i for i in items if i["dish_name"] == item["name"]), None)
    quantity = current_item["quantity"] if current_item else 1

    bot.answer_callback_query(
        call.id,
        f"✅ {item['name']} добавлено в корзину (всего: {quantity} шт)"
    )


# ─── Поиск ──────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_SEARCH_DISH)
def search_start(message):
    bot.send_message(message.chat.id, "Введите название блюда или его часть:")
    bot.register_next_step_handler(message, _search_process)


def _search_process(message):
    query = (message.text or "").strip()
    if not query:
        bot.send_message(message.chat.id, "Пустой запрос — отмена.")
        return
    dishes = db.search_menu(query)
    if not dishes:
        bot.send_message(message.chat.id, "Ничего не найдено.")
        return
    markup = InlineKeyboardMarkup()
    for d in dishes:
        discount = db.get_discount(d["id"])
        final = db.apply_discount(d["price"], discount)
        if discount:
            lbl = (f"{d['name']} — {fmt_money(d['price'])} → "
                   f"{fmt_money(final)} ₽ {fmt_discount(discount)}")
        else:
            lbl = f"{d['name']} — {fmt_money(final)} ₽"
        markup.add(InlineKeyboardButton(lbl, callback_data=f"add_to_cart|{d['id']}"))
    bot.send_message(message.chat.id, "🔎 Результаты:", reply_markup=markup)


# ════════════════════════════════════════════════════════════════════
#  Корзина и оплата
# ════════════════════════════════════════════════════════════════════

def render_cart(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    items = db.get_cart(user_id)
    if not items:
        return "🛒 Ваша корзина пуста.", InlineKeyboardMarkup()

    lines = []
    total = 0.0

    for it in items:
        subtotal = it["price"] * it["quantity"]
        total += subtotal

        # Форматируем строку с количеством
        if it["quantity"] > 1:
            lines.append(
                f"• {it['dish_name']} — *{it['quantity']} шт* × {fmt_money(it['price'])} ₽ = {fmt_money(subtotal)} ₽")
        else:
            lines.append(f"• {it['dish_name']} — {fmt_money(it['price'])} ₽")

    text = "🛒 *Ваша корзина:*\n" + "\n".join(lines) + f"\n\n💰 *Итого:* {fmt_money(total)} ₽"

    markup = InlineKeyboardMarkup(row_width=2)

    # Добавляем кнопки для каждого блюда для управления количеством
    for it in items:
        markup.add(
            InlineKeyboardButton(f"➖ {it['dish_name']}", callback_data=f"cart_decr|{it['dish_name']}"),
            InlineKeyboardButton(f"➕ {it['dish_name']}", callback_data=f"cart_incr|{it['dish_name']}")
        )

    markup.add(InlineKeyboardButton("💳 Выбрать способ оплату", callback_data="show_payment_options"))

    if user_id in user_payments:
        markup.add(InlineKeyboardButton("✅ Подтвердить заказ", callback_data="confirm_order"))

    return text, markup


@bot.callback_query_handler(func=lambda c: c.data.startswith(("cart_incr|", "cart_decr|")))
def cb_cart_quantity(call):
    """Обработчик увеличения/уменьшения количества товара в корзине."""
    action, dish_name = call.data.split("|", 1)
    user_id = call.message.chat.id

    if action == "cart_incr":
        # Получаем цену блюда из текущей корзины или из меню
        items = db.get_cart(user_id)
        current_item = next((item for item in items if item["dish_name"] == dish_name), None)

        if current_item:
            # Увеличиваем количество на 1
            db.add_to_cart(user_id, dish_name, current_item["price"], 1)
        else:
            # Если блюда нет в корзине - добавляем из меню
            menu_item = db.search_menu(dish_name)
            if menu_item:
                discount = db.get_discount(menu_item[0]["id"])
                price = db.apply_discount(menu_item[0]["price"], discount)
                db.add_to_cart(user_id, dish_name, price, 1)

    elif action == "cart_decr":
        # Уменьшаем количество на 1 или удаляем полностью
        db.remove_from_cart(user_id, dish_name, 1)

    # Обновляем отображение корзины
    text, markup = render_cart(user_id)
    try:
        bot.edit_message_text(
            text,
            chat_id=user_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=markup)

    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: m.text == B.BTN_OPEN_CART)
def open_cart(message):
    text, markup = render_cart(message.chat.id)

    # Добавляем информацию о количестве позиций
    items_count = db.get_cart_items_count(message.chat.id)
    if items_count > 0:
        text = f"🛒 *Ваша корзина* ({items_count} шт)\n" + text.split("\n", 1)[1]

    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text == B.BTN_CLEAR_CART)
def clear_cart_handler(message):
    db.clear_cart(message.chat.id)
    bot.send_message(message.chat.id, "🗑 Корзина очищена.")


@bot.callback_query_handler(func=lambda c: c.data == "show_payment_options")
def show_payment_options(call):
    user_id = call.message.chat.id

    # Пересчитываем актуальную сумму корзины
    cart_items = db.get_cart(user_id)
    total = 0.0
    for it in cart_items:
        total += it["price"] * it["quantity"]

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Перевод 💳", callback_data="pay_card"))
    markup.add(InlineKeyboardButton("Наличными 💵", callback_data="pay_cash"))
    markup.add(InlineKeyboardButton("<< Назад в корзину", callback_data="back_to_cart"))

    text = f"🛒 *Сумма заказа:* {fmt_money(total)} ₽\n\n💳 Способ оплаты:"

    try:
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data in ("pay_card", "pay_cash", "pay_later"))
def cb_select_payment(call):
    user_id = call.message.chat.id
    mapping = {"pay_card": "Перевод 💳", "pay_cash": "Наличными 💵"}
    user_payments[user_id] = mapping[call.data]

    # Пересчитываем актуальную сумму корзины
    cart_items = db.get_cart(user_id)
    total = 0.0
    for it in cart_items:
        total += it["price"] * it["quantity"]

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Подтвердить заказ", callback_data="confirm_order"))
    markup.add(InlineKeyboardButton("<< Назад в корзину", callback_data="back_to_cart"))

    bot.edit_message_text(
        f"*Способ оплаты:* {mapping[call.data]}\n"
        f"*Сумма заказа:* {fmt_money(total)} ₽\n\n"
        f"Нажмите «Подтвердить заказ» ниже 👇",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
        reply_markup=markup,
    )

@bot.callback_query_handler(func=lambda c: c.data == "back_to_cart")
def cb_back_to_cart(call):
    text, markup = render_cart(call.message.chat.id)
    try:
        bot.edit_message_text(text, chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


# ─── Подтверждение заказа ───────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "confirm_order")
def cb_confirm_order(call):
    user_id = call.message.chat.id

    if not require_consent(user_id):
        bot.answer_callback_query(call.id, "Нужно согласие на ПДн", show_alert=True)
        return

    if user_id not in user_payments:
        bot.answer_callback_query(call.id, "Сначала выберите способ оплаты", show_alert=True)
        return

    phone, address = db.get_user_contact_info(user_id)
    if not phone or not address:
        bot.answer_callback_query(call.id, show_alert=True,
                                  text="Сначала заполните профиль (📱🏠).")
        return

    cart_items = db.get_cart(user_id)
    if not cart_items:
        bot.answer_callback_query(call.id, "Корзина пуста", show_alert=True)
        return

    courier_chat_id = db.get_user_preferred_courier(user_id)
    if not courier_chat_id:
        bot.answer_callback_query(call.id, "Сначала выберите Доставщика (🚴)", show_alert=True)
        return

    # Сразу отвечаем на callback, пока не истёк
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    payment_method = user_payments[user_id]

    # ПЕРЕСЧИТЫВАЕМ ОБЩУЮ СУММУ с учётом количества!
    total = 0.0
    for it in cart_items:
        total += it["price"] * it["quantity"]

    order_number = generate_order_number()

    # Сохраняем данные для финального шага
    user_payments[user_id] = {
        "method": payment_method,
        "total": total,  # ← теперь правильная сумма!
        "order_number": order_number,
        "courier_chat_id": courier_chat_id,
        "step": "awaiting_comment",
    }

    try:
        bot.delete_message(user_id, call.message.message_id)
    except Exception:
        pass

    # Кнопка "Без комментария"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Без комментария ▶", callback_data="skip_comment"))

    bot.send_message(
        user_id,
        "📝 *Комментарий к заказу*\n\n"
        "Напишите комментарий к заказу\n\n"
        "Или нажмите кнопку ниже, чтобы пропустить.",
        parse_mode="Markdown",
        reply_markup=markup,
    )


def _send_order_to_courier(order_number: str, courier_chat_id: int) -> None:
    """Отправить заказ курьеру + запустить таймер 5 минут на реассайнмент."""
    order = db.get_order(order_number)
    if not order:
        return

    user_id = order["user_id"]
    pii = db.get_user_pii(user_id)
    name = pii["name"] or "—"
    phone = pii["phone"] or "—"
    address = pii["address"] or "—"

    # Получаем корзину с количеством
    cart_items = db.get_cart(user_id)
    items_text = ""
    order_total = 0.0

    if cart_items:
        lines = []
        for it in cart_items:
            subtotal = it["price"] * it["quantity"]
            order_total += subtotal
            if it["quantity"] > 1:
                lines.append(
                    f"• {it['dish_name']} — *{it['quantity']} шт* × {fmt_money(it['price'])} ₽ = {fmt_money(subtotal)} ₽"
                )
            else:
                lines.append(f"• {it['dish_name']} — {fmt_money(it['price'])} ₽")
        items_text = "\n*Состав:*\n" + "\n".join(lines)

    try:
        comment = order["comment"]
    except (KeyError, IndexError):
        comment = None

    text = (
        f"*Новый заказ:* `{order_number}`\n"
        f"*Имя:* {name}\n"
        f"*Адрес:* {address}\n"
        f"*Телефон:* +{phone}\n"
        f"*Сумма:* {fmt_money(order_total)} ₽\n"
        f"*Оплата:* {order['payment_method']}\n"
    )
    if comment:
        text += f"📝 *Комментарий:* {comment}\n"
    text += (
        f"{items_text}\n\n"
        f"⏱ У вас 5 минут на принятие заказа.\n"
        f"ℹ️ Пользователь может отменить заказ до его принятия."
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Принять", callback_data=f"order_accept|{order_number}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"order_reject|{order_number}"),
    )

    try:
        msg = bot.send_message(courier_chat_id, text, parse_mode="Markdown", reply_markup=markup)
        db.set_courier_message_id(order_number, msg.message_id)
    except Exception as e:
        logger.error("Не удалось отправить заказ Доставщику %s: %s", courier_chat_id, e)
        _try_reassign(order_number, fail_reason="недоступен")
        return

    # Таймер на 5 минут
    logger.info("Запускаю таймер для заказа %s на %s секунд", order_number, ORDER_TIMEOUT_SEC)
    t = threading.Timer(ORDER_TIMEOUT_SEC, _on_order_timeout, args=(order_number,))
    t.daemon = True
    t.start()


def _finalize_order(user_id: int, comment: str = None):
    """Создаёт заказ с учётом комментария."""
    payment_data = user_payments[user_id]
    payment_method = payment_data["method"]
    order_number = payment_data["order_number"]
    courier_chat_id = payment_data["courier_chat_id"]

    # Получаем корзину с количеством
    cart_items = db.get_cart(user_id)

    # ПЕРЕСЧИТЫВАЕМ ОБЩУЮ СУММУ с учётом количества!
    total = 0.0
    items_text = []

    for it in cart_items:
        subtotal = it["price"] * it["quantity"]
        total += subtotal

        if it["quantity"] > 1:
            items_text.append(
                f"• {it['dish_name']} — *{it['quantity']} шт* × {fmt_money(it['price'])} ₽ = {fmt_money(subtotal)} ₽"
            )
        else:
            items_text.append(f"• {it['dish_name']} — {fmt_money(it['price'])} ₽")

    # Сохраняем заказ в БД
    db.create_order(user_id, order_number, total, payment_method, courier_chat_id, comment)

    # При переводе — клиенту телефон курьера для перевода
    if payment_method == "Перевод 💳":
        courier = db.get_courier_by_chat_id(courier_chat_id)
        pay_phone = (courier["payment_phone"] if courier and courier["payment_phone"]
                     else "не указан, уточните у Доставщика")
        client_text = (
                f"*🥘 Ваш заказ:* `{order_number}`\n"
                f"*Состав:*\n" + "\n".join(items_text) + "\n\n"
                f"*💳 Способ оплаты:* перевод\n\n"
                f"📱 *Телефон для перевода:* `{pay_phone}`\n"
                f"💰 *Сумма:* {fmt_money(total)} ₽\n\n"
                f"⚠️ *В комментарии к переводу обязательно укажите номер заказа* "
                f"`{order_number}`.\n\n*Ищем доставщика…*"
        )
    else:
        client_text = (
                f"*🥘 Ваш заказ:* `{order_number}`\n"
                f"*Состав:*\n" + "\n".join(items_text) + "\n\n"
                                                         f"*💵 Способ оплаты:* наличными\n"
                                                         f"*Сумма:* {fmt_money(total)} ₽\n\n"
                                                         f"Передайте сумму Доставщику при получении.\n\n*Ищем доставщика…*"
        )

    if comment:
        client_text += f"\n📝 *Комментарий:* {comment}"

    # Добавляем кнопку отмены заказа
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_order|{order_number}"))

    msg = bot.send_message(user_id, client_text, parse_mode="Markdown", reply_markup=markup)
    db.set_order_message_id(order_number, msg.message_id)

    _send_order_to_courier(order_number, courier_chat_id)
    user_payments.pop(user_id, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel_order|"))
def cb_cancel_order(call):
    """Отмена заказа пользователем (до принятия курьером)."""
    order_number = call.data.split("|")[1]
    user_id = call.message.chat.id

    # Получаем заказ
    order = db.get_order(order_number)
    if not order:
        bot.answer_callback_query(call.id, "Заказ не найден", show_alert=True)
        return

    # Проверяем статус заказа (можно отменить только waiting)
    if order["status"] != "waiting":
        status = order["status"]
        if status == "Принято":
            bot.answer_callback_query(call.id, "❌ Заказ уже принят Доставщиком и не может быть отменён", show_alert=True)
        elif status == "Доставлено":
            bot.answer_callback_query(call.id, "✅ Заказ уже доставлен", show_alert=True)
        else:
            bot.answer_callback_query(call.id, f"❌ Заказ не может быть отменён (статус: {status})", show_alert=True)
        return

    # Обновляем статус заказа (НО НЕ ОЧИЩАЕМ КОРЗИНУ!)
    db.update_order_status(order_number, "Отменён")

    # Получаем ID курьера
    courier_id = order["courier_id"]

    # Создаём клавиатуру с действиями
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🛒 Повторить заказ", callback_data=f"repeat_order|{order_number}"),
        InlineKeyboardButton("🗑 Очистить корзину", callback_data="clear_cart_after_cancel"),
        InlineKeyboardButton("<< Назад в корзину", callback_data="back_to_cart"),

    )

    # Обновляем сообщение у пользователя
    try:
        bot.edit_message_text(
            f"❌ *Заказ* `{order_number}` *отменён*",
            chat_id=user_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception:
        bot.send_message(
            user_id,
            f"❌ Заказ `{order_number}` отменён.",
            parse_mode="Markdown",
            reply_markup=markup
        )

    # Отправляем уведомление курьеру
    if courier_id and order["courier_msg_id"]:
        try:
            bot.edit_message_text(
                f"❌ *Заказ* `{order_number}` *отменён пользователем*\n\n"
                f"Заказ больше не актуален.",
                chat_id=courier_id,
                message_id=order["courier_msg_id"],
                parse_mode="Markdown"
            )
        except Exception:
            try:
                bot.send_message(
                    courier_id,
                    f"❌ Заказ `{order_number}` отменён пользователем.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    db.log_user_action(user_id, f"cancelled_order:{order_number}")
    bot.answer_callback_query(call.id, "✅ Заказ отменён, корзина сохранена")


@bot.callback_query_handler(func=lambda c: c.data.startswith("repeat_order|"))
def cb_repeat_order(call):
    """Повторить отменённый заказ (с той же корзиной)."""
    order_number = call.data.split("|")[1]
    user_id = call.message.chat.id
    db.clear_rejected_couriers(order_number)
    # Получаем заказ
    order = db.get_order(order_number)
    if not order:
        bot.answer_callback_query(call.id, "Заказ не найден", show_alert=True)
        return
    # Проверяем, что корзина не пуста
    cart_items = db.get_cart(user_id)
    if not cart_items:
        bot.answer_callback_query(call.id, "Корзина пуста", show_alert=True)
        return

    # Проверяем профиль
    phone, address = db.get_user_contact_info(user_id)
    if not phone or not address:
        bot.answer_callback_query(call.id, "Сначала заполните профиль (📱🏠)", show_alert=True)
        return

    # Проверяем курьера
    courier_chat_id = db.get_user_preferred_courier(user_id)
    if not courier_chat_id:
        bot.answer_callback_query(call.id, "Сначала выберите Доставщика (🚴)", show_alert=True)
        return

    # Получаем метод оплаты (из отменённого заказа)
    payment_method = order["payment_method"]

    # Пересчитываем сумму
    total = 0.0
    for it in cart_items:
        total += it["price"] * it["quantity"]

    # Создаём новый номер заказа
    new_order_number = generate_order_number()

    # Сохраняем данные
    user_payments[user_id] = {
        "method": payment_method,
        "total": total,
        "order_number": new_order_number,
        "courier_chat_id": courier_chat_id,
        "step": "awaiting_comment"
    }

    # Удаляем текущее сообщение
    try:
        bot.delete_message(user_id, call.message.message_id)
    except Exception:
        pass

    # Запрашиваем комментарий (как при обычном заказе)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Без комментария ▶", callback_data="skip_comment"))

    bot.send_message(
        user_id,
        "📝 *Комментарий к заказу*\n\n"
        "Напишите комментарий к заказу\n\n"
        "Или нажмите кнопку ниже, чтобы пропустить.",
        parse_mode="Markdown",
        reply_markup=markup,
    )

    bot.answer_callback_query(call.id, "Оформляем повторный заказ...")


@bot.callback_query_handler(func=lambda c: c.data == "clear_cart_after_cancel")
def cb_clear_cart_after_cancel(call):
    """Очистить корзину после отмены заказа."""
    user_id = call.message.chat.id
    db.clear_cart(user_id)

    bot.edit_message_text(
        "🗑 Корзина очищена.\n\n"
        "Вы можете начать новый заказ с помощью кнопки «📋 Смотреть меню».",
        chat_id=user_id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )



    bot.send_message(
        user_id,
        "Выберите действие:",
    )

    bot.answer_callback_query(call.id, "Корзина очищена")


@bot.callback_query_handler(func=lambda c: c.data == "back_to_main_menu")
def cb_back_to_main_menu(call):
    """Вернуться в главное меню."""
    send_main_menu(call.message.chat.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)




@bot.callback_query_handler(func=lambda c: c.data == "skip_comment")
def skip_comment(call):
    """Пропустить комментарий и создать заказ."""
    user_id = call.message.chat.id
    # Сначала удаляем сообщение с кнопкой, потом создаём заказ
    try:
        bot.delete_message(user_id, call.message.message_id)
    except Exception:
        pass
    _finalize_order(user_id, comment=None)
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: m.chat.id in user_payments
                                    and isinstance(user_payments[m.chat.id], dict)
                                    and user_payments[m.chat.id].get("step") == "awaiting_comment")
def receive_comment(message):
    """Получаем комментарий от пользователя."""
    user_id = message.chat.id
    comment = (message.text or "").strip()

    if len(comment) > 500:
        bot.send_message(user_id, "⚠️ Комментарий слишком длинный. Максимум 500 символов. Попробуйте ещё раз:")
        return

    # Удаляем сообщение с запросом комментария
    try:
        # Ищем сообщение с кнопкой "Без комментария" и удаляем его
        # Оно было отправлено последним перед этим сообщением
        bot.delete_message(user_id, message.message_id - 1)
    except Exception:
        pass

    # Удаляем сообщение пользователя с комментарием
    try:
        bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    _finalize_order(user_id, comment=comment if comment else None)


def _on_order_timeout(order_number: str) -> None:
    """Сработал таймер 5 минут."""
    order = db.get_order(order_number)
    if not order:
        logger.info("Заказ %s не найден", order_number)
        return

    status = order["status"] if order["status"] else "waiting"
    logger.info("Таймаут заказа %s, статус: %s", order_number, status)

    if status != "waiting":
        logger.info("Заказ %s уже не waiting (%s), пропускаем", order_number, status)
        return

    logger.info("Таймаут заказа %s — реассайн", order_number)

    # Добавляем текущего курьера в список отказавшихся (по таймауту)
    current_courier = order["courier_id"]
    if current_courier:
        db.add_rejected_courier(order_number, current_courier)

    _try_reassign(order_number, fail_reason="не успел принять")


def _try_reassign(order_number: str, fail_reason: str) -> None:
    """Передать заказ следующему курьеру по рейтингу."""
    order = db.get_order(order_number)
    if not order:
        return
    user_id = order["user_id"]
    current_courier = order["courier_id"]

    # У текущего курьера убираем кнопки/обновляем текст
    if order["courier_msg_id"] and current_courier:
        try:
            bot.edit_message_text(
                f"⌛ Заказ `{order_number}` передан другому Доставщику ({fail_reason}).",
                chat_id=current_courier,
                message_id=order["courier_msg_id"],
                parse_mode="Markdown",
            )
        except Exception:
            try:
                bot.send_message(current_courier,
                                 f"⌛ Заказ `{order_number}` передан другому Доставщику.",
                                 parse_mode="Markdown")
            except Exception:
                pass

    # Получаем список всех курьеров и список отказавшихся
    all_couriers = db.get_all_courier_chat_ids()
    rejected = db.get_rejected_couriers(order_number)

    # Исключаем текущего курьера (он уже в rejected или будет добавлен позже)
    exclude = list(set(rejected + ([current_courier] if current_courier else [])))

    # Проверяем, остались ли доступные курьеры
    available_couriers = [c for c in all_couriers if c not in exclude]

    if not available_couriers:
        # Нет доступных курьеров - отменяем заказ
        db.update_order_status(order_number, "Отменён (нет Доставщиков)")

        # Создаём клавиатуру с действиями
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🛒 Повторить заказ", callback_data=f"repeat_order|{order_number}"),
            InlineKeyboardButton("🗑 Очистить корзину", callback_data="clear_cart_after_cancel"),
            InlineKeyboardButton("<< Назад в корзину", callback_data="back_to_cart"),
        )

        # Обновляем сообщение пользователя
        if order["message_id"]:
            try:
                bot.edit_message_text(
                    f"❌ *Заказ* `{order_number}` *отменён*\n"
                    f"😞 К сожалению,нету доступных Доставщиков.\n"
                    f"Вы можете повторить заказ, очистить корзину или вернуться к её редактированию.",
                    chat_id=user_id,
                    message_id=order["message_id"],
                    parse_mode="Markdown",
                    reply_markup=markup
                )
            except Exception:
                bot.send_message(
                    user_id,
                    f"❌ Заказ `{order_number}` отменён. Нет доступных Доставщиков.\n"
                    f"Вы можете повторить заказ, очистить корзину или вернуться к её редактированию.",
                    parse_mode="Markdown",
                    reply_markup=markup
                )
        else:
            bot.send_message(
                user_id,
                f"❌ Заказ `{order_number}` отменён. Нет доступных Доставщиков.\n"
                f"Вы можете повторить заказ, очистить корзину или вернуться к её редактированию.",
                parse_mode="Markdown",
                reply_markup=markup
            )
        return

    # Находим следующего курьера
    next_id = db.next_courier_for_reassign(exclude)

    if not next_id:
        # Теоретически не должно случиться, но на всякий случай
        logger.error(f"Не найден следующий Доставщик для заказа {order_number}, хотя available_couriers не пуст")
        return

    db.reassign_order(order_number, next_id)

    try:
        if order["message_id"]:
            order_fresh = db.get_order(order_number)
            new_text = (
                f"*🥘 Ваш заказ:* `{order_number}`\n"
                f"*Способ оплаты:* {order_fresh['payment_method']}\n"
                f"*Сумма:* {fmt_money(order_fresh['total_price'])} ₽\n\n"
                f"Передаём заказ другому Доставщику…"
            )

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_order|{order_number}"))
            bot.edit_message_text(new_text, chat_id=user_id,
                                  message_id=order["message_id"],
                                  parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка обновления сообщения пользователя: {e}")

    _send_order_to_courier(order_number, next_id)


# ─── Принятие / отклонение / завершение заказа ──────────────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith(("order_accept|", "order_reject|", "order_complete|")))
def cb_order_action(call):
    action, order_number = call.data.split("|", 1)
    courier_id = call.message.chat.id

    order = db.get_order(order_number)
    if not order:
        bot.answer_callback_query(call.id, "Заказ не найден", show_alert=True)
        return

    user_id = order["user_id"]

    # Проверяем, не отменён ли заказ
    if order["status"] == "Отменён":
        bot.answer_callback_query(call.id, "❌ Этот заказ уже отменён пользователем", show_alert=True)
        try:
            bot.edit_message_reply_markup(courier_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    # Защита от повторного срабатывания у того, у кого заказ уже отобрали
    if order["courier_id"] != courier_id and action != "order_complete":
        bot.answer_callback_query(call.id, "Этот заказ уже передан другому Доставщику", show_alert=True)
        try:
            bot.edit_message_reply_markup(courier_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    try:
        bot.edit_message_reply_markup(courier_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    if action == "order_accept":
        # Проверяем ещё раз перед принятием
        order_check = db.get_order(order_number)
        if order_check["status"] == "Отменён":
            bot.answer_callback_query(call.id, "❌ Заказ был отменён пользователем", show_alert=True)
            return

        client_msg_id = db.update_order_status(order_number, "Принято")
        logger.info("Заказ %s принят Доставщиком %s", order_number, courier_id)

        if client_msg_id:
            # Обновляем сообщение пользователя - убираем кнопку отмены
            try:
                bot.edit_message_text(
                    f"*🥘 Ваш заказ:* `{order_number}`\n"
                    f"*Статус:* ✅ Принят Доставщиком!\n\n"
                    f"Доставщик уже в пути! Ожидайте доставку.",
                    chat_id=user_id,
                    message_id=client_msg_id,
                    parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(user_id, f"✅ Заказ {order_number} принят Доставщиком!")

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "✅ Завершить", callback_data=f"order_complete|{order_number}",
        ))
        msg = bot.send_message(courier_id, f"✅ Заказ `{order_number}` принят.\n\nПосле доставки нажмите «Завершить».",
                               parse_mode="Markdown", reply_markup=markup)
        db.set_courier_message_id(order_number, msg.message_id)


    elif action == "order_reject":

        # Проверяем, не отменён ли заказ

        order_check = db.get_order(order_number)

        if order_check["status"] == "Отменён":
            bot.answer_callback_query(call.id, "❌ Заказ уже отменён", show_alert=True)

            return

        # Добавляем курьера в список отказавшихся

        db.add_rejected_courier(order_number, courier_id)

        # Получаем список всех курьеров и список отказавшихся

        all_couriers = db.get_all_courier_chat_ids()

        rejected = db.get_rejected_couriers(order_number)

        # Проверяем, остались ли ещё курьеры

        available_couriers = [c for c in all_couriers if c not in rejected]

        if not available_couriers:

            # Нет доступных курьеров - отменяем заказ

            db.update_order_status(order_number, "Отменён (нет Доставщиков)")

            # Уведомляем пользователя с кнопками

            user_id = order_check["user_id"]

            markup = InlineKeyboardMarkup(row_width=2)

            markup.add(

                InlineKeyboardButton("🛒 Повторить заказ", callback_data=f"repeat_order|{order_number}"),

                InlineKeyboardButton("🗑 Очистить корзину", callback_data="clear_cart_after_cancel"),

                InlineKeyboardButton("<< Назад в корзину", callback_data="back_to_cart"),

            )

            if order_check["message_id"]:

                try:

                    bot.edit_message_text(

                        f"❌ *Заказ* `{order_number}` *отменён*\n"
                        f"😞 К сожалению, нету доступных Доставщиков\n"
                        f"Вы можете повторить заказ, очистить корзину или вернуться к её редактированию.",

                        chat_id=user_id,

                        message_id=order_check["message_id"],

                        parse_mode="Markdown",

                        reply_markup=markup

                    )

                except Exception:

                    bot.send_message(

                        user_id,

                        f"❌ Заказ `{order_number}` отменён. Нет доступных Доставщиков.\n"
                        f"Вы можете повторить заказ, очистить корзину или вернуться к её редактированию.",

                        parse_mode="Markdown",

                        reply_markup=markup

                    )

            else:

                bot.send_message(

                    user_id,

                    f"❌ Заказ `{order_number}` отменён. Нет доступных Доставщиков.\n"
                    f"Вы можете повторить заказ, очистить корзину или вернуться к её редактированию.",

                    parse_mode="Markdown",

                    reply_markup=markup

                )



            return

        # Если есть ещё курьеры - пробуем реассайн

        _try_reassign(order_number, fail_reason="отклонил")

        bot.send_message(courier_id, f"❌ Вы отклонили заказ `{order_number}`.",

                         parse_mode="Markdown")

    elif action == "order_complete":
        client_msg_id = db.update_order_status(order_number, "Доставлено")
        db.clear_cart(user_id)

        if client_msg_id:
            try:
                bot.edit_message_text(
                    f"*Заказ* `{order_number}` *доставлен!*\nСпасибо, что выбрали нас 🙌",
                    chat_id=user_id, message_id=client_msg_id, parse_mode="Markdown",
                )
            except Exception:
                bot.send_message(user_id, f"✅ Заказ {order_number} доставлен!")

        try:
            bot.delete_message(courier_id, call.message.message_id)
        except Exception:
            pass

        payment_markup = InlineKeyboardMarkup(row_width=2)
        payment_markup.add(
            InlineKeyboardButton("✅ Оплачено", callback_data=f"order_paid|{order_number}"),
            InlineKeyboardButton("❌ Не оплачено", callback_data=f"order_unpaid|{order_number}"),
        )
        bot.send_message(
            courier_id,
            f"✅ Заказ `{order_number}` завершён!\n\nКлиент оплатил заказ?",
            parse_mode="Markdown",
            reply_markup=payment_markup,
        )

        _ask_rating(user_id, order_number, courier_id)


@bot.message_handler(commands=["cancel_all_waiting"])
def admin_cancel_all_waiting(message):
    """Отмена всех ожидающих заказов (только для админа)."""
    if not is_admin(message.chat.id):
        return

    # Получаем все ожидающие заказы
    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT order_number, user_id, courier_id, courier_msg_id, message_id FROM orders WHERE status = 'waiting'")
        orders = c.fetchall()

    if not orders:
        bot.send_message(message.chat.id, "Нет ожидающих заказов.")
        return

    confirm_markup = InlineKeyboardMarkup()
    confirm_markup.add(
        InlineKeyboardButton("✅ Да, отменить все", callback_data="confirm_cancel_all"),
        InlineKeyboardButton("❌ Нет", callback_data="cancel_cancel_all")
    )

    bot.send_message(
        message.chat.id,
        f"⚠️ Найдено {len(orders)} ожидающих заказов.\n\n"
        f"Вы уверены, что хотите отменить их все?",
        reply_markup=confirm_markup
    )


@bot.callback_query_handler(func=lambda c: c.data == "confirm_cancel_all")
def confirm_cancel_all(call):
    if not is_admin(call.message.chat.id):
        return

    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT order_number, user_id, courier_id, courier_msg_id, message_id FROM orders WHERE status = 'waiting'")
        orders = c.fetchall()

    cancelled_count = 0
    for order in orders:
        order_number = order["order_number"]
        user_id = order["user_id"]
        courier_id = order["courier_id"]

        # Обновляем статус
        db.update_order_status(order_number, "Отменён (админом)")

        # Уведомляем пользователя
        if order["message_id"]:
            try:
                bot.edit_message_text(
                    f"❌ *Заказ* `{order_number}` *отменён администратором*",
                    chat_id=user_id,
                    message_id=order["message_id"],
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        # Уведомляем курьера
        if courier_id and order["courier_msg_id"]:
            try:
                bot.edit_message_text(
                    f"❌ *Заказ* `{order_number}` *отменён администратором*",
                    chat_id=courier_id,
                    message_id=order["courier_msg_id"],
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        cancelled_count += 1

    bot.edit_message_text(
        f"✅ Отменено заказов: {cancelled_count}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "cancel_cancel_all")
def cancel_cancel_all(call):
    bot.edit_message_text(
        "❌ Отмена отменена.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id)
# ════════════════════════════════════════════════════════════════════
#  Рейтинг курьеров
# ════════════════════════════════════════════════════════════════════

def _ask_rating(user_id: int, order_number: str, courier_id: int) -> None:
    markup = InlineKeyboardMarkup(row_width=5)
    buttons = [InlineKeyboardButton(
        "⭐" * stars, callback_data=f"rate|{order_number}|{courier_id}|{stars}",
    ) for stars in range(1, 6)]
    markup.row(*buttons)
    try:
        bot.send_message(
            user_id,
            f"🙏 Оцените работу Доставщика по заказу `{order_number}`:",
            parse_mode="Markdown", reply_markup=markup,
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("rate|"))
def cb_rate(call):
    try:
        _, order_number, courier_id_str, stars_str = call.data.split("|")
        courier_id = int(courier_id_str)
        stars = int(stars_str)
    except ValueError:
        return
    user_id = call.message.chat.id
    ok = db.save_rating(order_number, courier_id, user_id, stars)
    if ok:
        try:
            bot.edit_message_text(
                f"Спасибо за оценку! Вы поставили {'⭐' * stars}.",
                chat_id=user_id, message_id=call.message.message_id,
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Оценка сохранена")
    else:
        bot.answer_callback_query(call.id, "Вы уже оценивали этот заказ", show_alert=True)


# Добавить обработчик в bot.py
@bot.message_handler(func=lambda m: m.text == B.BTN_MY_PHONE)
def courier_show_my_phone(message):
    """Показать курьеру его номер для переводов."""
    if not is_courier(message.chat.id):
        bot.send_message(message.chat.id, "Эта функция доступна только Доставщикам.")
        return

    phone = db.get_courier_phone(message.chat.id)
    courier = db.get_courier_by_chat_id(message.chat.id)
    name = courier["name"] if courier else "Доставщик"

    if phone:
        bot.send_message(
            message.chat.id,
            f"📞 *{name}*, ваш номер для переводов:\n"
            f"`{phone}`\n\n"
            f"⚠️ Этот номер видят клиенты при выборе оплаты переводом.\n"
            f"Если номер неверный, обратитесь к администратору.",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(
            message.chat.id,
            f"⚠️ *{name}*, у вас не указан номер для переводов.\n\n"
            f"Пожалуйста, обратитесь к администратору, чтобы он добавил ваш номер.",
            parse_mode="Markdown"
        )
# ════════════════════════════════════════════════════════════════════
#  Выбор курьера (с рейтингом)
# ════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == B.BTN_CHOOSE_COURIER)
def choose_courier(message):
    couriers = db.get_couriers_by_rating()
    if not couriers:
        bot.send_message(message.chat.id, "⚠️ Доставщики пока не добавлены.")
        return
    markup = InlineKeyboardMarkup()
    for c in couriers:
        rating_str = fmt_rating(c["avg_rating"], c["ratings_count"])
        markup.add(InlineKeyboardButton(
            f"{c['name']} · {rating_str}",
            callback_data=f"pick_courier|{c['telegram_chat_id']}",
        ))
    bot.send_message(message.chat.id, "Выберите Доставщика (сортировка по рейтингу):",
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("pick_courier|"))
def cb_pick_courier(call):
    courier_id = int(call.data.split("|")[1])
    db.set_user_preferred_courier(call.message.chat.id, courier_id)
    bot.edit_message_text(
        "✅ Доставщик выбран. Ваши заказы пойдут к нему.",
        chat_id=call.message.chat.id, message_id=call.message.message_id,
    )


# ════════════════════════════════════════════════════════════════════
#  Чат с курьером (пользователь -> курьер)
# ════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == B.BTN_CHAT_COURIER)
def msg_to_courier_start(message):
    courier_chat_id = db.get_user_preferred_courier(message.chat.id)
    if not courier_chat_id:
        bot.send_message(message.chat.id, "⚠️ Сначала выберите Доставщика (🚴).")
        return
    bot.send_message(message.chat.id, "✉ Введите текст сообщения Доставщику:")
    bot.register_next_step_handler(message, _send_to_courier, courier_chat_id)


def _send_to_courier(message, courier_chat_id):
    user_id = message.chat.id
    pii = db.get_user_pii(user_id)
    name = pii["name"] or f"ID {user_id}"

    user_last_messages[user_id] = {"name": name, "chat_id": user_id}

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💬 Ответить", callback_data=f"reply_to|{user_id}"))
    try:
        bot.send_message(
            courier_chat_id,
            f"✉ *Сообщение от {name}:*\n\n{message.text}",
            parse_mode="Markdown", reply_markup=markup,
        )
        bot.send_message(user_id, "✅ Сообщение отправлено Доставщику.")
    except Exception as e:
        logger.error("Чат с Доставщиком: %s", e)
        bot.send_message(user_id, "⚠️ Не удалось отправить, попробуйте позже.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("reply_to|"))
def cb_reply_to_user(call):
    courier_id = call.message.chat.id
    user_id = int(call.data.split("|")[1])
    user_data = user_last_messages.get(user_id, {})
    admin_state[courier_id] = {
        "state": "awaiting_reply",
        "user_id": user_id,
        "user_name": user_data.get("name", f"ID {user_id}"),
    }
    bot.send_message(courier_id, "✍ Введите ваш ответ:")
    try:
        bot.edit_message_reply_markup(courier_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass


@bot.message_handler(func=lambda m: isinstance(admin_state.get(m.chat.id), dict)
                     and admin_state[m.chat.id].get("state") == "awaiting_reply")
def courier_reply(message):
    state = admin_state.pop(message.chat.id)
    try:
        bot.send_message(
            state["user_id"],
            f"🚴 *Ответ от Доставщика:*\n\n{message.text}",
            parse_mode="Markdown",
        )
        bot.send_message(message.chat.id, f"✅ Ответ отправлен {state['user_name']}.")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Не удалось отправить: {e}")


# ════════════════════════════════════════════════════════════════════
#  Поддержка (FAQ + ссылка на админа)
# ════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == B.BTN_SUPPORT)
def support_faq(message):
    """Показывает FAQ и кнопку для связи с админом."""
    user_id = message.chat.id

    faq_text = (
        "💡 *Поддержка и помощь*\n\n"
        "🔹 *Частые вопросы:*\n\n"
        "❓ *Как сделать заказ?*\n"
        "Нажмите «📋 Смотреть меню» → выберите блюда → «🛒 Корзина» → «✅ Подтвердить заказ».\n\n"
        "❓ *Как оплатить заказ?*\n"
        "В корзине нажмите «💳 Выбрать способ оплату» — доступны перевод на карту или наличные Доставщику.\n\n"
        "❓ *Где мой заказ?*\n"
        "Нажмите «📦 Мои заказы» — там виден статус всех ваших заказов.\n\n"
        "❓ *Как связаться с Доставщиком?*\n"
        "Нажмите «📩 Чат с доставщиком» и напишите сообщение.\n\n"
        "❓ *Как изменить адрес доставки?*\n"
        "Нажмите «🏠 Сменить адрес» и введите новый адрес.\n\n"
        "❓ *Не нашли ответ?*\n"
        "Нажмите кнопку ниже, чтобы написать администратору напрямую."
    )

    markup = InlineKeyboardMarkup(row_width=1)

    # Кнопка с ссылкой на админа
    # Если у админа есть username — используем url
    admin_username = os.getenv("ADMIN_USERNAME", "")
    if admin_username:
        markup.add(InlineKeyboardButton(
            "📝 Написать в поддержку",
            url=f"https://t.me/{admin_username.lstrip('@')}",
        ))
    else:
        # Если username нет — отправляем контакт админа
        markup.add(InlineKeyboardButton(
            "📝 Написать в поддержку",
            callback_data="sup_contact_admin",
        ))

    markup.add(InlineKeyboardButton("❌ Закрыть", callback_data="faq_close"))

    bot.send_message(user_id, faq_text, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "sup_contact_admin")
def support_contact_admin(call):
    """Отправляет контакт админа (если нет username)."""
    user_id = call.message.chat.id
    admin_id = config.ADMIN_CHAT_ID

    bot.answer_callback_query(call.id)

    # Сообщаем ID админа
    bot.send_message(
        user_id,
        f"📝 *Напишите администратору:*\n\n"
        f"Перейдите по ссылке: `tg://user?id={admin_id}`\n\n"
        f"Или найдите в Telegram: `{admin_id}`\n\n"
        f"Опишите вашу проблему — администратор ответит вам в ближайшее время.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@bot.callback_query_handler(func=lambda c: c.data == "faq_close")
def faq_close(call):
    """Закрыть FAQ."""
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)

# ════════════════════════════════════════════════════════════════════
#  Поддержка (через Telegram, без WebApp)
# ════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════
#  Мои заказы / История
# ════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == B.BTN_MY_ORDERS)
def my_orders(message):
    orders = db.get_user_orders(message.chat.id, limit=10)
    if not orders:
        bot.send_message(message.chat.id, "У вас пока нет заказов.")
        return
    lines = ["*Ваши последние заказы:*"]
    for o in orders:
        lines.append(f"`{o['order_number']}` — {o['total_price']} ₽ — {o['status']}")
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == B.BTN_ORDER_HISTORY)
def order_history_ask_format(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("TXT"), KeyboardButton("DOCX"))
    markup.add(KeyboardButton(B.BTN_BACK))
    bot.send_message(message.chat.id, "В каком формате выгрузить историю?", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text in ("TXT", "DOCX"))
@bot.message_handler(func=lambda m: m.text in ("TXT", "DOCX"))
def order_history_send(message):
    user_id = message.chat.id
    orders = db.get_user_orders(user_id, limit=1000)
    if not orders:
        bot.send_message(user_id, "У вас пока нет заказов.")
        return

    fmt = message.text
    suffix = f".{fmt.lower()}"

    # Используем контекстный менеджер
    with temporary_file(prefix=f"history_{user_id}_", suffix=suffix) as tmp_file:
        if fmt == "TXT":
            with open(tmp_file, "w", encoding="utf-8") as f:
                for o in orders:
                    f.write(f"Заказ {o['order_number']} | {o['created_at']} | "
                            f"{o['total_price']} ₽ | {o['status']}\n")
        else:  # DOCX
            doc = Document()
            doc.add_heading("История заказов", level=1)
            for o in orders:
                doc.add_paragraph(
                    f"№{o['order_number']} от {o['created_at']}\n"
                    f"Сумма: {o['total_price']} ₽\nСтатус: {o['status']}\n"
                    "—" * 30
                )
            doc.save(tmp_file)

        # Отправляем файл
        with open(tmp_file, "rb") as f:
            bot.send_document(user_id, f)

    # Файл автоматически удалён после выхода из контекста
    send_main_menu(user_id)


# ════════════════════════════════════════════════════════════════════
#  Админ: меню (добавить / удалить / заморозить)
# ════════════════════════════════════════════════════════════════════


@bot.message_handler(func=lambda m: m.text == B.BTN_ADD_DISH)
def admin_add_dish(message):
    if not is_admin(message.chat.id): return

    categories = db.get_categories()
    if not categories:
        bot.send_message(message.chat.id, "⚠️ Сначала добавьте категории.")
        return

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"➕ {cat['name']}",
            callback_data=f"add_dish_cat|{cat['id']}",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    bot.send_message(message.chat.id, "Выберите категорию для блюда:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("add_dish_cat|"))
def add_dish_category(call):
    if not is_admin(call.message.chat.id): return
    category_id = int(call.data.split("|")[1])
    admin_state[call.message.chat.id] = {"action": "add_dish", "category_id": category_id}

    bot.send_message(call.message.chat.id, "Введите название блюда:")
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: isinstance(admin_state.get(m.chat.id), dict)
                                    and admin_state[m.chat.id].get("action") == "add_dish")
def add_dish_name(message):
    if not is_admin(message.chat.id): return
    dish_name = (message.text or "").strip()
    if not dish_name:
        bot.send_message(message.chat.id, "⚠️ Пустое название, отмена.")
        admin_state.pop(message.chat.id, None)
        return

    admin_state[message.chat.id]["dish_name"] = dish_name
    admin_state[message.chat.id]["action"] = "add_dish_price"
    bot.send_message(message.chat.id, "Введите цену:")


@bot.message_handler(func=lambda m: isinstance(admin_state.get(m.chat.id), dict)
                                    and admin_state[m.chat.id].get("action") == "add_dish_price")
def add_dish_price(message):
    if not is_admin(message.chat.id): return
    try:
        price = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Не число. Отмена.")
        admin_state.pop(message.chat.id, None)
        return

    state = admin_state.pop(message.chat.id)
    category_id = state["category_id"]
    dish_name = state["dish_name"]
    category_name = db.get_category_name(category_id)

    db.add_menu_item(dish_name, price, category_id)
    bot.send_message(message.chat.id, f"✅ «{dish_name}» добавлено в категорию «{category_name}» за {price} ₽.")


@bot.message_handler(func=lambda m: m.text == B.BTN_DELETE_DISH)
def admin_del_dish(message):
    if not is_admin(message.chat.id): return

    categories = db.get_categories()
    if not categories:
        bot.send_message(message.chat.id, "Нет категорий.")
        return

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"❌ {cat['name']}",
            callback_data=f"del_dish_cat|{cat['id']}|0",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    markup.row(InlineKeyboardButton("<< Назад", callback_data="del_dish_back"))

    bot.send_message(message.chat.id, "❌ Выберите категорию для удаления блюд:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_dish_cat|"))
def del_dish_category(call):
    if not is_admin(call.message.chat.id): return
    _, category_id, page = call.data.split("|")
    _show_del_dishes(call.message.chat.id, int(category_id), int(page),
                     edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def _show_del_dishes(chat_id, category_id, page=0, edit_message_id=None):
    """Показывает блюда категории для удаления с пагинацией."""
    category_name = db.get_category_name(category_id)

    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM menu WHERE category_id = ?", (category_id,))
        total = c.fetchone()["n"]
        total_pages = max(1, ceil(total / DISHES_PER_PAGE))
        page = max(0, min(page, total_pages - 1))
        c.execute("SELECT id, name, price, frozen FROM menu WHERE category_id = ? ORDER BY name LIMIT ? OFFSET ?",
                  (category_id, DISHES_PER_PAGE, page * DISHES_PER_PAGE))
        dishes = c.fetchall()

    if not dishes:
        bot.send_message(chat_id, f"В категории «{category_name}» нет блюд.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for d in dishes:
        try:
            status = "🔒 " if d["frozen"] else ""
        except (IndexError, KeyError):
            status = ""
        markup.add(InlineKeyboardButton(
            f"❌ {status}{d['name']} — {fmt_money(d['price'])} ₽",
            callback_data=f"del_dish|{d['id']}|{category_id}",
        ))

    nav = []
    nav_prefix = f"del_page|{category_id}"
    if page > 0:
        nav.append(InlineKeyboardButton("⏪", callback_data=f"{nav_prefix}|0"))
        nav.append(InlineKeyboardButton("◀", callback_data=f"{nav_prefix}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"{nav_prefix}|{page + 1}"))
        nav.append(InlineKeyboardButton("⏩", callback_data=f"{nav_prefix}|{total_pages - 1}"))
    if len(nav) > 1:
        markup.row(*nav)
    markup.add(InlineKeyboardButton("<< К категориям", callback_data="del_back_cat"))

    if edit_message_id:
        try:
            bot.edit_message_text(
                f"❌ {category_name} — выберите блюдо для удаления:",
                chat_id=chat_id, message_id=edit_message_id, reply_markup=markup,
            )
            return
        except Exception:
            pass
    bot.send_message(chat_id, f"❌ {category_name} — выберите блюдо для удаления:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("del_page|"))
def cb_del_page(call):
    if not is_admin(call.message.chat.id): return
    _, category_id, page = call.data.split("|")
    _show_del_dishes(call.message.chat.id, int(category_id), int(page),
                     edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("del_dish|"))
def del_dish_confirm(call):
    if not is_admin(call.message.chat.id): return
    _, dish_id, category_id = call.data.split("|")
    dish_id = int(dish_id)
    category_id = int(category_id)

    item = db.get_menu_item_by_id(dish_id)
    if not item:
        bot.answer_callback_query(call.id, "Блюдо не найдено")
        return

    try:
        cat_id = item["category_id"]
    except (IndexError, KeyError):
        cat_id = category_id

    db.delete_menu_item(item["name"], cat_id)

    bot.answer_callback_query(call.id, f"«{item['name']}» удалено", show_alert=True)
    _show_del_dishes(call.message.chat.id, category_id, 0, edit_message_id=call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data == "del_back_cat")
def cb_del_back_cat(call):
    if not is_admin(call.message.chat.id): return

    categories = db.get_categories()
    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"❌ {cat['name']}",
            callback_data=f"del_dish_cat|{cat['id']}|0",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    markup.row(InlineKeyboardButton("<< Назад", callback_data="del_dish_back"))

    bot.edit_message_text(
        "❌ Выберите категорию для удаления блюд:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "del_dish_back")
def cb_del_dish_back(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)





@bot.callback_query_handler(func=lambda c: c.data == "del_dish_cancel")
def del_dish_cancel(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: m.text == B.BTN_FREEZE_DISH)
def admin_freeze_list(message):
    if not is_admin(message.chat.id): return
    _show_categories_for_freeze(message.chat.id, mode="freeze")


@bot.message_handler(func=lambda m: m.text == B.BTN_UNFREEZE_DISH)
def admin_unfreeze_list(message):
    if not is_admin(message.chat.id): return
    _show_categories_for_freeze(message.chat.id, mode="unfreeze")


def _show_categories_for_freeze(chat_id, mode, edit_message_id=None):
    categories = db.get_categories()
    if not categories:
        bot.send_message(chat_id, "Нет категорий.")
        return

    cb_prefix = "frz_cat" if mode == "freeze" else "unfrz_cat"
    title = "🥶 Выберите категорию для скрытия:" if mode == "freeze" else "☀️ Выберите категорию для возврата:"
    emoji = "🥶" if mode == "freeze" else "☀️"

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"{emoji} {cat['name']}",
            callback_data=f"{cb_prefix}|{cat['id']}|0",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    markup.row(InlineKeyboardButton("<< Назад", callback_data="frz_back"))

    if edit_message_id:
        try:
            bot.edit_message_text(title, chat_id=chat_id, message_id=edit_message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, title, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("frz_back"))
def cb_freeze_back(call):
    if not is_admin(call.message.chat.id): return
    mode = call.data.split("|")[1] if "|" in call.data else "freeze"
    _show_categories_for_freeze(call.message.chat.id, mode, edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("frz_cat|") or c.data.startswith("unfrz_cat|"))
def cb_freeze_category(call):
    if not is_admin(call.message.chat.id): return
    prefix, category_id, page = call.data.split("|")
    mode = "freeze" if prefix == "frz_cat" else "unfreeze"

    if mode == "freeze":
        items = db.get_menu_items_available(int(category_id))
    else:
        items = db.get_menu_items_frozen(int(category_id))

    category_name = db.get_category_name(int(category_id))

    if not items:
        bot.answer_callback_query(call.id, f"В категории «{category_name}» нет блюд", show_alert=True)
        return

    _show_freeze_list(
        call.message.chat.id,
        int(page),
        mode,
        items=items,
        category_id=int(category_id),
        title_prefix=category_name,
        edit_message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id)


def _show_freeze_list(chat_id: int, page: int, mode: str,
                      items=None, category_id=None, title_prefix="",
                      edit_message_id=None) -> None:
    """Показывает список блюд с пагинацией."""
    if mode == "freeze":
        title = f"🥶 {title_prefix} — выберите блюдо для скрытия:"
        cb_prefix = "freeze"
        empty_text = "✅ Все блюда уже скрыты или меню пустое."
    else:
        title = f"☀️ {title_prefix} — выберите блюдо для возврата:"
        cb_prefix = "unfreeze"
        empty_text = "Нет скрытых блюд."

    if not items:
        bot.send_message(chat_id, empty_text)
        return

    total_pages = max(1, (len(items) + DISHES_PER_PAGE - 1) // DISHES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start, end = page * DISHES_PER_PAGE, (page + 1) * DISHES_PER_PAGE

    markup = InlineKeyboardMarkup(row_width=1)
    for it in items[start:end]:
        markup.add(InlineKeyboardButton(
            f"{it['name']} — {fmt_money(it['price'])} ₽",
            callback_data=f"{cb_prefix}_do|{it['id']}|{category_id or 0}",
        ))

    nav = []
    nav_prefix = f"{cb_prefix}_p|{category_id or 0}"
    if page > 0:
        nav.append(InlineKeyboardButton("⏪", callback_data=f"{nav_prefix}|0"))
        nav.append(InlineKeyboardButton("◀", callback_data=f"{nav_prefix}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"{nav_prefix}|{page + 1}"))
        nav.append(InlineKeyboardButton("⏩", callback_data=f"{nav_prefix}|{total_pages - 1}"))
    if len(nav) > 1:
        markup.row(*nav)
    markup.add(InlineKeyboardButton("<< К категориям", callback_data=f"frz_back|{mode}"))

    if edit_message_id:
        try:
            bot.edit_message_text(title, chat_id=chat_id,
                                  message_id=edit_message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, title, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("freeze_p|") or c.data.startswith("unfreeze_p|"))
def cb_freeze_paginate(call):
    if not is_admin(call.message.chat.id): return
    parts = call.data.split("|")
    prefix = parts[0]
    category_id = int(parts[1])
    page = int(parts[2])
    mode = "freeze" if prefix == "freeze_p" else "unfreeze"

    if mode == "freeze":
        items = db.get_menu_items_available(category_id)
    else:
        items = db.get_menu_items_frozen(category_id)

    category_name = db.get_category_name(category_id)
    _show_freeze_list(
        call.message.chat.id, page, mode,
        items=items, category_id=category_id,
        title_prefix=category_name,
        edit_message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("freeze_do|") or c.data.startswith("unfreeze_do|"))
def cb_freeze_apply(call):
    if not is_admin(call.message.chat.id): return
    parts = call.data.split("|")
    prefix = parts[0]
    menu_id = int(parts[1])
    category_id = int(parts[2])
    freeze = (prefix == "freeze_do")

    name = db.set_dish_frozen_by_id(menu_id, freeze)
    if name:
        word = "скрыто" if freeze else "снова доступно"
        bot.answer_callback_query(call.id, f"✅ {name}: {word}")

        mode = "freeze" if freeze else "unfreeze"
        if mode == "freeze":
            items = db.get_menu_items_available(category_id)
        else:
            items = db.get_menu_items_frozen(category_id)

        category_name = db.get_category_name(category_id) if category_id else ""
        _show_freeze_list(
            call.message.chat.id, 0, mode,
            items=items, category_id=category_id,
            title_prefix=category_name,
            edit_message_id=call.message.message_id,
        )
    else:
        bot.answer_callback_query(call.id, "Блюдо не найдено", show_alert=True)



@bot.message_handler(func=lambda m: m.text == B.BTN_FREEZE_ALL)
def admin_freeze_all(message):
    if not is_admin(message.chat.id): return
    n = db.set_all_dishes_frozen(True)
    bot.send_message(message.chat.id, f"🥶 Скрыто блюд: {n}.")


@bot.message_handler(func=lambda m: m.text == B.BTN_UNFREEZE_ALL)
def admin_unfreeze_all(message):
    if not is_admin(message.chat.id): return
    n = db.set_all_dishes_frozen(False)
    bot.send_message(message.chat.id, f"☀️ Возвращено блюд: {n}.")


@bot.message_handler(func=lambda m: m.text == B.BTN_LIST_FROZEN)
def admin_list_frozen(message):
    if not is_admin(message.chat.id): return
    rows = db.get_menu_items_frozen()
    if not rows:
        bot.send_message(message.chat.id, "Нет скрытых блюд.")
        return
    text = "📜 *Скрытые блюда:*\n" + "\n".join(
        f"• {r['name']} — {fmt_money(r['price'])} ₽" for r in rows
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


# ─── Управление фото блюд ───────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_ADD_PHOTO)
def admin_add_photo_start(message):
    """Начать добавление фото для блюда."""
    if not is_admin(message.chat.id):
        return

    # Показываем категории для выбора блюда
    categories = db.get_categories()
    if not categories:
        bot.send_message(message.chat.id, "⚠️ Нет категорий с блюдами.")
        return

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        # Получаем количество блюд в категории
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM menu WHERE category_id = ? AND frozen = 0", (cat["id"],))
            count = c.fetchone()[0]

        if count > 0:
            row_buttons.append(InlineKeyboardButton(
                f"📸 {cat['name']} ({count})",
                callback_data=f"photo_cat|{cat['id']}|0",
            ))

        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            if row_buttons:
                markup.row(*row_buttons)
                row_buttons = []

    if not markup.keyboard:
        bot.send_message(message.chat.id, "⚠️ Нет доступных блюд для добавления фото.")
        return

    bot.send_message(
        message.chat.id,
        "📸 Выберите категорию с блюдом для добавления фото:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("photo_cat|"))
def cb_photo_select_category(call):
    """Выбор категории для добавления фото."""
    if not is_admin(call.message.chat.id):
        return

    _, category_id, page = call.data.split("|")
    _show_dishes_for_photo(call.message.chat.id, int(category_id), int(page),
                           edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def _show_dishes_for_photo(chat_id: int, category_id: int, page: int = 0, edit_message_id=None):
    """Показать блюда категории для добавления фото."""
    category_name = db.get_category_name(category_id)

    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM menu WHERE category_id = ? AND frozen = 0", (category_id,))
        total = c.fetchone()["n"]
        total_pages = max(1, ceil(total / DISHES_PER_PAGE))
        page = max(0, min(page, total_pages - 1))

        c.execute("""
            SELECT id, name, price, photo 
            FROM menu 
            WHERE category_id = ? AND frozen = 0 
            ORDER BY name 
            LIMIT ? OFFSET ?
        """, (category_id, DISHES_PER_PAGE, page * DISHES_PER_PAGE))
        dishes = c.fetchall()

    if not dishes:
        bot.send_message(chat_id, f"В категории «{category_name}» нет доступных блюд.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for d in dishes:
        has_photo = "📸" if d["photo"] else "📷"
        markup.add(InlineKeyboardButton(
            f"{has_photo} {d['name']} — {fmt_money(d['price'])} ₽",
            callback_data=f"photo_dish|{d['id']}"
        ))

    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"photo_page|{category_id}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"photo_page|{category_id}|{page + 1}"))
    if len(nav) > 1:
        markup.row(*nav)

    markup.add(InlineKeyboardButton("<< К категориям", callback_data="photo_back_cat"))

    if edit_message_id:
        try:
            bot.edit_message_text(
                f"📸 {category_name} — выберите блюдо для добавления фото:",
                chat_id=chat_id,
                message_id=edit_message_id,
                reply_markup=markup
            )
            return
        except Exception:
            pass

    bot.send_message(
        chat_id,
        f"📸 {category_name} — выберите блюдо для добавления фото:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("photo_page|"))
def cb_photo_page(call):
    """Пагинация при выборе блюда для фото."""
    if not is_admin(call.message.chat.id):
        return
    _, category_id, page = call.data.split("|")
    _show_dishes_for_photo(call.message.chat.id, int(category_id), int(page),
                           edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("photo_dish|"))
def cb_photo_select_dish(call):
    """Выбрано блюдо для добавления фото."""
    if not is_admin(call.message.chat.id):
        return

    menu_id = int(call.data.split("|")[1])
    dish = db.get_menu_item_by_id(menu_id)

    if not dish:
        bot.answer_callback_query(call.id, "Блюдо не найдено", show_alert=True)
        return

    # Сохраняем состояние
    admin_state[call.message.chat.id] = {
        "action": "add_photo",
        "menu_id": menu_id,
        "dish_name": dish["name"]
    }

    bot.edit_message_text(
        f"📸 *Добавление фото для:* {dish['name']}\n\n"
        f"Отправьте фото для этого блюда.\n\n"
        f"*(Можно отправить как обычное фото, так и файлом)*",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "photo_back_cat")
def cb_photo_back_cat(call):
    """Назад к категориям для выбора фото."""
    if not is_admin(call.message.chat.id):
        return

    categories = db.get_categories()
    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM menu WHERE category_id = ? AND frozen = 0", (cat["id"],))
            count = c.fetchone()[0]

        if count > 0:
            row_buttons.append(InlineKeyboardButton(
                f"📸 {cat['name']} ({count})",
                callback_data=f"photo_cat|{cat['id']}|0",
            ))

        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            if row_buttons:
                markup.row(*row_buttons)
                row_buttons = []

    bot.edit_message_text(
        "📸 Выберите категорию с блюдом для добавления фото:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


# ─── Удаление фото ─────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_DELETE_PHOTO)
def admin_delete_photo_start(message):
    """Начать удаление фото блюда."""
    if not is_admin(message.chat.id):
        return

    categories = db.get_categories()
    if not categories:
        bot.send_message(message.chat.id, "⚠️ Нет категорий с блюдами.")
        return

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        # Получаем количество блюд с фото в категории
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM menu WHERE category_id = ? AND photo IS NOT NULL", (cat["id"],))
            count = c.fetchone()[0]

        if count > 0:
            row_buttons.append(InlineKeyboardButton(
                f"🗑 {cat['name']} ({count})",
                callback_data=f"delphoto_cat|{cat['id']}|0",
            ))

        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            if row_buttons:
                markup.row(*row_buttons)
                row_buttons = []

    if not markup.keyboard:
        bot.send_message(message.chat.id, "⚠️ Нет блюд с фото для удаления.")
        return

    bot.send_message(
        message.chat.id,
        "🗑 Выберите категорию для удаления фото:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("delphoto_cat|"))
def cb_delphoto_select_category(call):
    """Выбор категории для удаления фото."""
    if not is_admin(call.message.chat.id):
        return

    _, category_id, page = call.data.split("|")
    _show_dishes_for_delete_photo(call.message.chat.id, int(category_id), int(page),
                                  edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def _show_dishes_for_delete_photo(chat_id: int, category_id: int, page: int = 0, edit_message_id=None):
    """Показать блюда с фото для удаления."""
    category_name = db.get_category_name(category_id)

    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM menu WHERE category_id = ? AND photo IS NOT NULL", (category_id,))
        total = c.fetchone()["n"]
        total_pages = max(1, ceil(total / DISHES_PER_PAGE))
        page = max(0, min(page, total_pages - 1))

        c.execute("""
            SELECT id, name, price, photo 
            FROM menu 
            WHERE category_id = ? AND photo IS NOT NULL 
            ORDER BY name 
            LIMIT ? OFFSET ?
        """, (category_id, DISHES_PER_PAGE, page * DISHES_PER_PAGE))
        dishes = c.fetchall()

    if not dishes:
        bot.send_message(chat_id, f"В категории «{category_name}» нет блюд с фото.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for d in dishes:
        markup.add(InlineKeyboardButton(
            f"🗑 {d['name']} — {fmt_money(d['price'])} ₽",
            callback_data=f"delphoto_dish|{d['id']}"
        ))

    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"delphoto_page|{category_id}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"delphoto_page|{category_id}|{page + 1}"))
    if len(nav) > 1:
        markup.row(*nav)

    markup.add(InlineKeyboardButton("<< К категориям", callback_data="delphoto_back_cat"))

    if edit_message_id:
        try:
            bot.edit_message_text(
                f"🗑 {category_name} — выберите блюдо для удаления фото:",
                chat_id=chat_id,
                message_id=edit_message_id,
                reply_markup=markup
            )
            return
        except Exception:
            pass

    bot.send_message(
        chat_id,
        f"🗑 {category_name} — выберите блюдо для удаления фото:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("delphoto_page|"))
def cb_delphoto_page(call):
    """Пагинация при удалении фото."""
    if not is_admin(call.message.chat.id):
        return
    _, category_id, page = call.data.split("|")
    _show_dishes_for_delete_photo(call.message.chat.id, int(category_id), int(page),
                                  edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("delphoto_dish|"))
def cb_delphoto_confirm(call):
    """Подтверждение удаления фото."""
    if not is_admin(call.message.chat.id):
        return

    menu_id = int(call.data.split("|")[1])
    dish = db.get_menu_item_by_id(menu_id)

    if not dish:
        bot.answer_callback_query(call.id, "Блюдо не найдено", show_alert=True)
        return

    db.set_dish_photo(menu_id, None)

    bot.edit_message_text(
        f"✅ Фото для блюда «{dish['name']}» удалено!",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id, "Фото удалено")


@bot.callback_query_handler(func=lambda c: c.data == "delphoto_back_cat")
def cb_delphoto_back_cat(call):
    """Назад к категориям для удаления фото."""
    if not is_admin(call.message.chat.id):
        return

    categories = db.get_categories()
    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM menu WHERE category_id = ? AND photo IS NOT NULL", (cat["id"],))
            count = c.fetchone()[0]

        if count > 0:
            row_buttons.append(InlineKeyboardButton(
                f"🗑 {cat['name']} ({count})",
                callback_data=f"delphoto_cat|{cat['id']}|0",
            ))

        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            if row_buttons:
                markup.row(*row_buttons)
                row_buttons = []

    bot.edit_message_text(
        "🗑 Выберите категорию для удаления фото:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(content_types=["photo"])
def handle_dish_photo(message):
    """Обработка отправленного фото для блюда."""
    if not is_admin(message.chat.id):
        return

    state = admin_state.get(message.chat.id, {})
    if state.get("action") != "add_photo":
        return

    # Получаем file_id самого большого фото
    photo = message.photo[-1]
    file_id = photo.file_id
    menu_id = state["menu_id"]
    dish_name = state["dish_name"]

    # Сохраняем фото
    db.set_dish_photo(menu_id, file_id)
    db.log_user_action(message.chat.id, f"added_photo:{dish_name}")

    bot.send_message(
        message.chat.id,
        f"✅ Фото для блюда «{dish_name}» сохранено!"
    )

    # Очищаем состояние
    admin_state.pop(message.chat.id, None)
# ─── Категории ───────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_CATEGORIES)
def admin_categories_menu(message):
    if not is_admin(message.chat.id): return

    categories = db.get_categories()

    text = "📁 *Категории меню*\n\n"
    if categories:
        for cat in categories:
            text += f"• {cat['name']}\n"
    else:
        text += "Нет категорий.\n"

    text += "\nВыберите действие:"

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ Добавить категорию", callback_data="cat_add"),
        InlineKeyboardButton("❌ Удалить категорию", callback_data="cat_del_list"),
    )
    markup.add(InlineKeyboardButton("❌Закрыть", callback_data="cat_close"))

    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "cat_add")
def category_add_start(call):
    if not is_admin(call.message.chat.id): return
    admin_state[call.message.chat.id] = {"action": "add_category"}
    bot.send_message(call.message.chat.id, "Введите название новой категории:")
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: isinstance(admin_state.get(m.chat.id), dict)
                                    and admin_state[m.chat.id].get("action") == "add_category")
def category_add_name(message):
    if not is_admin(message.chat.id): return
    name = (message.text or "").strip()
    if not name:
        bot.send_message(message.chat.id, "⚠️ Название не может быть пустым.")
        return

    db.add_category(name)
    admin_state.pop(message.chat.id, None)
    bot.send_message(message.chat.id, f"✅ Категория «{name}» добавлена!")


@bot.callback_query_handler(func=lambda c: c.data == "cat_del_list")
def category_del_list(call):
    if not is_admin(call.message.chat.id): return

    categories = db.get_categories()
    if not categories:
        bot.answer_callback_query(call.id, "Нет категорий")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for cat in categories:
        markup.add(InlineKeyboardButton(
            f"❌ {cat['name']}",
            callback_data=f"cat_del|{cat['id']}",
        ))
    markup.add(InlineKeyboardButton("❌Отмена", callback_data="cat_close"))

    bot.edit_message_text(
        "⚠️ Выберите категорию для удаления (все блюда в ней тоже удалятся):",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: m.text == "📋 Список Доставщиков")
def admin_list_couriers(message):
    """Показать список всех курьеров с их номерами."""
    if not is_admin(message.chat.id):
        return

    couriers = db.get_all_couriers_with_phones()
    if not couriers:
        bot.send_message(message.chat.id, "Список Доставщиков пуст.")
        return

    text = "📋 *Список Доставщиков:*\n\n"
    for courier in couriers:
        phone = courier["payment_phone"] or "❌ не указан"
        text += f"👤 *{courier['name']}*\n"
        text += f"🆔 ID: `{courier['telegram_chat_id']}`\n"
        text += f"📞 Номер: `{phone}`\n"
        text += "─" * 30 + "\n"

    # Отправляем частями если текст длинный
    for i in range(0, len(text), 3500):
        safe_send_message(message.chat.id, text[i:i + 3500], parse_mode="Markdown")
@bot.callback_query_handler(func=lambda c: c.data.startswith("cat_del|"))
def category_delete(call):
    if not is_admin(call.message.chat.id): return
    category_id = int(call.data.split("|")[1])

    name = db.get_category_name(category_id)
    db.delete_category(category_id)

    bot.edit_message_text(
        f"✅ Категория «{name}» и все блюда в ней удалены!",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id, f"Категория «{name}» удалена")


@bot.callback_query_handler(func=lambda c: c.data == "cat_close")
def category_close(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)
# ─── Управление скидками ─────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_DISCOUNTS)
def admin_discounts_menu(message):
    if not is_admin(message.chat.id): return

    discounts = db.get_all_discounts()

    markup = InlineKeyboardMarkup(row_width=1)

    if discounts:
        text = "🏷 *Активные скидки:*\n\n"
        for d in discounts:
            if d["kind"] == "percent":
                val_str = f"{d['value']}%"
            else:
                val_str = f"{d['value']} ₽"
            text += f"• {d['name']} — скидка {val_str}"
            if d["valid_until"]:
                text += f" (до {d['valid_until']})"
            text += "\n"
    else:
        text = "🏷 Нет активных скидок.\n"

    text += "\nВыберите действие:"

    markup.add(InlineKeyboardButton("➕ Добавить скидку", callback_data="discount_add"))
    if discounts:
        markup.add(InlineKeyboardButton("❌ Убрать скидку", callback_data="discount_remove_list"))

    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "discount_add")
def cb_discount_add_list(call):
    if not is_admin(call.message.chat.id): return
    _show_categories_for_discount(call.message.chat.id, edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def _show_categories_for_discount(chat_id, edit_message_id=None):
    categories = db.get_categories()
    if not categories:
        bot.send_message(chat_id, "Нет категорий.")
        return

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"🏷 {cat['name']}",
            callback_data=f"disc_cat|{cat['id']}|0",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    markup.row(InlineKeyboardButton("<< Назад", callback_data="disc_cancel"))

    if edit_message_id:
        try:
            bot.edit_message_text("🏷 Выберите категорию:",
                                  chat_id=chat_id, message_id=edit_message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, "🏷 Выберите категорию:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "disc_back_cat")
def cb_discount_back_cat(call):
    if not is_admin(call.message.chat.id): return
    _show_categories_for_discount(call.message.chat.id, edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)
@bot.callback_query_handler(func=lambda c: c.data.startswith("disc_cat|"))
def cb_discount_category(call):
    if not is_admin(call.message.chat.id): return
    _, category_id, page = call.data.split("|")
    _show_discount_dish_page(call.message.chat.id, int(category_id), int(page),
                             edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def _show_discount_dish_page(chat_id: int, category_id: int = None, page: int = 0, edit_message_id=None):
    """Показывает список блюд для добавления скидки с пагинацией."""
    category_name = db.get_category_name(category_id) if category_id else "Все"

    with db.conn_ctx() as conn:
        c = conn.cursor()
        if category_id:
            c.execute("SELECT COUNT(*) AS n FROM menu WHERE category_id = ? AND frozen = 0", (category_id,))
        else:
            c.execute("SELECT COUNT(*) AS n FROM menu WHERE frozen = 0")
        total = c.fetchone()["n"]
        total_pages = max(1, ceil(total / DISHES_PER_PAGE))
        page = max(0, min(page, total_pages - 1))

        if category_id:
            c.execute(
                "SELECT id, name, price FROM menu WHERE category_id = ? AND frozen = 0 ORDER BY name LIMIT ? OFFSET ?",
                (category_id, DISHES_PER_PAGE, page * DISHES_PER_PAGE))
        else:
            c.execute("SELECT id, name, price FROM menu WHERE frozen = 0 ORDER BY name LIMIT ? OFFSET ?",
                      (DISHES_PER_PAGE, page * DISHES_PER_PAGE))
        items = c.fetchall()

    if not items:
        bot.send_message(chat_id, "Нет доступных блюд.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for it in items:
        markup.add(InlineKeyboardButton(
            f"{it['name']} — {fmt_money(it['price'])} ₽",
            callback_data=f"disc_set|{it['id']}",
        ))

    nav = []
    nav_prefix = f"disc_page|{category_id or 0}"
    if page > 0:
        nav.append(InlineKeyboardButton("⏪", callback_data=f"{nav_prefix}|0"))
        nav.append(InlineKeyboardButton("◀", callback_data=f"{nav_prefix}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="disc_none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"{nav_prefix}|{page + 1}"))
        nav.append(InlineKeyboardButton("⏩", callback_data=f"{nav_prefix}|{total_pages - 1}"))
    if len(nav) > 1:
        markup.row(*nav)

    markup.add(InlineKeyboardButton("<< К категориям", callback_data="disc_back_cat"))
    markup.add(InlineKeyboardButton("❌Отмена", callback_data="disc_cancel"))

    if edit_message_id:
        try:
            bot.edit_message_text(
                f"🏷 {category_name} — выберите блюдо для скидки:",
                chat_id=chat_id, message_id=edit_message_id, reply_markup=markup,
            )
            return
        except Exception:
            pass

    bot.send_message(chat_id, f"🏷 {category_name} — выберите блюдо для скидки:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("disc_page|"))
def cb_discount_page(call):
    if not is_admin(call.message.chat.id): return
    _, category_id, page = call.data.split("|")
    _show_discount_dish_page(call.message.chat.id, int(category_id) if category_id != "0" else None,
                             int(page), edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("disc_set|"))
def cb_discount_set_type(call):
    if not is_admin(call.message.chat.id): return
    menu_id = int(call.data.split("|")[1])

    discount_state[call.message.chat.id] = {"menu_id": menu_id, "step": "type"}

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Процент %", callback_data="disc_type|percent"),
        InlineKeyboardButton("Рубли ₽", callback_data="disc_type|rub"),
    )

    bot.edit_message_text(
        "Выберите тип скидки:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("disc_type|"))
def cb_discount_type(call):
    if not is_admin(call.message.chat.id): return
    kind = call.data.split("|")[1]

    discount_state[call.message.chat.id]["kind"] = kind
    discount_state[call.message.chat.id]["step"] = "value"

    if kind == "percent":
        bot.send_message(call.message.chat.id, "Введите размер скидки в процентах (например, 15):")
    else:
        bot.send_message(call.message.chat.id, "Введите размер скидки в рублях (например, 100):")

    bot.answer_callback_query(call.id)


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.chat.id in discount_state and discount_state.get(m.chat.id, {}).get(
        "step") == "value")
def discount_input_value(message):
    if not is_admin(message.chat.id): return
    state = discount_state[message.chat.id]

    try:
        value = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Введите число.")
        return

    if state["kind"] == "percent" and (value <= 0 or value > 99):
        bot.send_message(message.chat.id, "⚠️ Процент должен быть от 1 до 99.")
        return
    if state["kind"] == "rub" and value <= 0:
        bot.send_message(message.chat.id, "⚠️ Сумма должна быть больше 0.")
        return

    state["value"] = value
    state["step"] = "duration"

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Бессрочно", callback_data="disc_dur|forever"),
        InlineKeyboardButton("1 день", callback_data="disc_dur|1"),
        InlineKeyboardButton("3 дня", callback_data="disc_dur|3"),
        InlineKeyboardButton("7 дней", callback_data="disc_dur|7"),
    )

    bot.send_message(
        message.chat.id,
        "Выберите срок действия скидки:",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("disc_dur|"))
def cb_discount_duration(call):
    if not is_admin(call.message.chat.id): return
    state = discount_state.get(call.message.chat.id, {})

    choice = call.data.split("|")[1]

    if choice == "forever":
        valid_until = None
    else:
        from datetime import datetime, timedelta
        days = int(choice)
        valid_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    db.set_discount(state["menu_id"], state["kind"], state["value"], valid_until)
    db.log_user_action(call.message.chat.id, f"discount_set:{state['menu_id']}")

    discount_state.pop(call.message.chat.id, None)

    bot.edit_message_text(
        "✅ Скидка установлена!",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id, "Скидка сохранена")


@bot.callback_query_handler(func=lambda c: c.data == "discount_remove_list")
def cb_discount_remove_list(call):
    if not is_admin(call.message.chat.id): return

    discounts = db.get_all_discounts()
    if not discounts:
        bot.answer_callback_query(call.id, "Нет активных скидок")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for d in discounts:
        if d["kind"] == "percent":
            val_str = f"{d['value']}%"
        else:
            val_str = f"{d['value']} ₽"
        markup.add(InlineKeyboardButton(
            f"❌ {d['name']} ({val_str})",
            callback_data=f"disc_remove|{d['menu_id']}",
        ))

    bot.edit_message_text(
        "Выберите скидку для удаления:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("disc_remove|"))
def cb_discount_remove(call):
    if not is_admin(call.message.chat.id): return
    menu_id = int(call.data.split("|")[1])

    db.remove_discount(menu_id)
    db.log_user_action(call.message.chat.id, f"discount_removed:{menu_id}")

    bot.edit_message_text(
        "✅ Скидка удалена.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id, "Скидка удалена")
# ─── Изменение цен ──────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_EDIT_PRICES)
def admin_edit_prices(message):
    if not is_admin(message.chat.id): return
    _show_categories_for_edit(message.chat.id)


def _show_categories_for_edit(chat_id, edit_message_id=None):
    categories = db.get_categories()
    if not categories:
        bot.send_message(chat_id, "Нет категорий.")
        return

    markup = InlineKeyboardMarkup()
    row_buttons = []

    for i, cat in enumerate(categories):
        row_buttons.append(InlineKeyboardButton(
            f"💰 {cat['name']}",
            callback_data=f"edit_cat|{cat['id']}|0",
        ))
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            markup.row(*row_buttons)
            row_buttons = []

    markup.row(InlineKeyboardButton("<< Назад", callback_data="edit_back"))

    if edit_message_id:
        try:
            bot.edit_message_text("💰 Выберите категорию для редактирования цен:",
                                  chat_id=chat_id, message_id=edit_message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, "💰 Выберите категорию для редактирования цен:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "edit_back_cat")
def cb_edit_back_cat(call):
    if not is_admin(call.message.chat.id): return
    _show_categories_for_edit(call.message.chat.id, edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_cat|"))
def cb_edit_category(call):
    if not is_admin(call.message.chat.id): return
    _, category_id, page = call.data.split("|")
    _show_dish_edit_page(call.message.chat.id, int(category_id), int(page),
                         edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def _show_dish_edit_page(chat_id: int, category_id: int, page: int = 0, edit_message_id=None):
    """Показывает блюда категории для редактирования цен."""
    category_name = db.get_category_name(category_id)

    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM menu WHERE category_id = ?", (category_id,))
        total = c.fetchone()["n"]
        total_pages = max(1, ceil(total / DISHES_PER_PAGE))
        page = max(0, min(page, total_pages - 1))
        c.execute("SELECT id, name, price FROM menu WHERE category_id = ? ORDER BY name LIMIT ? OFFSET ?",
                  (category_id, DISHES_PER_PAGE, page * DISHES_PER_PAGE))
        dishes = c.fetchall()

    if not dishes:
        bot.send_message(chat_id, f"В категории «{category_name}» нет блюд.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for d in dishes:
        markup.add(InlineKeyboardButton(
            f"{d['name']} — {fmt_money(d['price'])} ₽",
            callback_data=f"edit_price|{d['id']}",
        ))

    nav = []
    nav_prefix = f"edit_page|{category_id}"
    if page > 0:
        nav.append(InlineKeyboardButton("⏪", callback_data=f"{nav_prefix}|0"))
        nav.append(InlineKeyboardButton("◀", callback_data=f"{nav_prefix}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"{nav_prefix}|{page + 1}"))
        nav.append(InlineKeyboardButton("⏩", callback_data=f"{nav_prefix}|{total_pages - 1}"))
    if len(nav) > 1:
        markup.row(*nav)
    markup.add(InlineKeyboardButton("<< К категориям", callback_data="edit_back_cat"))

    if edit_message_id:
        try:
            bot.edit_message_text(
                f"💰 {category_name} — выберите блюдо:",
                chat_id=chat_id, message_id=edit_message_id, reply_markup=markup,
            )
            return
        except Exception:
            pass
    bot.send_message(chat_id, f"💰 {category_name} — выберите блюдо:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_page|"))
def cb_edit_page(call):
    if not is_admin(call.message.chat.id): return
    _, category_id, page = call.data.split("|")
    _show_dish_edit_page(call.message.chat.id, int(category_id), int(page),
                         edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "edit_back")
def cb_edit_back(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_price|"))
def cb_edit_price(call):
    if not is_admin(call.message.chat.id): return
    dish_id = int(call.data.split("|")[1])
    with db.conn_ctx() as conn:
        c = conn.cursor()
        c.execute("SELECT name, price FROM menu WHERE id = ?", (dish_id,))
        row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Блюдо не найдено", show_alert=True)
        return
    admin_edit_state[call.message.chat.id] = {"dish_id": dish_id, "name": row["name"],
                                              "old_price": row["price"]}
    bot.send_message(
        call.message.chat.id,
        f"*{row['name']}*\nТекущая цена: *{row['price']}* ₽\n\n✍ Введите новую цену:",
        parse_mode="Markdown",
    )


@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.chat.id in admin_edit_state)
def admin_save_new_price(message):
    state = admin_edit_state.pop(message.chat.id)
    try:
        new_price = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Введите число.")
        return
    db.update_dish_price(state["dish_id"], new_price)
    bot.send_message(
        message.chat.id,
        f"✅ Цена *{state['name']}*: {state['old_price']} → {new_price} ₽",
        parse_mode="Markdown",
    )


# ─── Курьеры (нанять/уволить) ───────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_HIRE_COURIER)
def admin_hire_courier(message):
    if not is_admin(message.chat.id): return
    bot.send_message(
        message.chat.id,
        "📇 Перешлите контакт Доставщика из своих контактов Telegram.\n\n"
        "⚠️ Доставщик должен сначала написать /start боту, иначе бот не сможет ему отправлять сообщения."
    )


def admin_hire_courier_contact(message):
    """Обработка контакта от админа для найма Доставщика."""
    if not is_admin(message.chat.id):
        return

    contact = message.contact
    if not contact:
        bot.send_message(message.chat.id, "⚠️ Не удалось получить контакт.")
        return

    courier_chat_id = contact.user_id
    if not courier_chat_id:
        bot.send_message(
            message.chat.id,
            "⚠️ У этого контакта нет Telegram ID. Возможно, это не пользователь Telegram.\n"
            "Попросите Доставщика сначала написать /start боту, затем повторите."
        )
        return

    courier_name = contact.first_name or ""
    if contact.last_name:
        courier_name += f" {contact.last_name}"
    if not courier_name:
        courier_name = f"Доставщик {courier_chat_id}"

    courier_phone = contact.phone_number or ""

    # Сохраняем во временное хранилище
    hire_state[message.chat.id] = {
        "chat_id": courier_chat_id,
        "name": courier_name,
        "phone": courier_phone,
    }

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Да", callback_data="hire_yes"),
        InlineKeyboardButton("❌ Нет", callback_data="hire_no"),
    )

    bot.send_message(
        message.chat.id,
        f"📋 Данные Доставщика:\n"
        f"• Имя: {courier_name}\n"
        f"• ID: `{courier_chat_id}`\n"
        f"• Телефон: {courier_phone or 'не указан'}\n\n"
        f"Добавляем?",
        parse_mode="Markdown",
        reply_markup=markup,
    )


# ─── Изменить номер телефона курьера для переводов ───────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_EDIT_COURIER_PHONE)
def admin_edit_courier_phone_start(message):
    """Начать изменение номера телефона курьера."""
    if not is_admin(message.chat.id):
        return

    couriers = db.get_all_couriers_with_phones()
    if not couriers:
        bot.send_message(message.chat.id, "⚠️ Список Доставщиков пуст. Сначала наймите Доставщиков.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for courier in couriers:
        name = courier["name"]
        phone = courier["payment_phone"] or "не указан"
        markup.add(InlineKeyboardButton(
            f"📱 {name} — {phone}",
            callback_data=f"edit_courier_phone|{courier['telegram_chat_id']}"
        ))

    bot.send_message(
        message.chat.id,
        "📱 Выберите Доставщика для изменения номера телефона для переводов:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_courier_phone|"))
def cb_edit_courier_phone_select(call):
    """Выбран курьер для изменения номера телефона."""
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    courier_chat_id = int(call.data.split("|")[1])
    courier = db.get_courier_by_chat_id(courier_chat_id)

    if not courier:
        bot.answer_callback_query(call.id, "Доставщик не найден", show_alert=True)
        return

    # Сохраняем состояние
    admin_state[call.message.chat.id] = {
        "action": "edit_courier_phone",
        "courier_chat_id": courier_chat_id,
        "courier_name": courier["name"],
        "current_phone": courier["payment_phone"]
    }

    current_phone = courier["payment_phone"] or "не указан"

    bot.edit_message_text(
        f"📱 *Изменение номера телефона для переводов*\n"
        f"👤 Доставщик: *{courier['name']}*\n"
        f"📞 Текущий номер: `{current_phone}`\n"
        f"✍️ Введите новый номер телефона в формате:\n"
        f"`79123456789`\n"
        f"Или отправьте контакт нажав на кнопку 📎",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: is_admin(m.chat.id) and
                                    isinstance(admin_state.get(m.chat.id), dict) and
                                    admin_state[m.chat.id].get("action") == "edit_courier_phone")
def admin_edit_courier_phone_input(message):
    """Получить новый номер телефона курьера."""
    state = admin_state[message.chat.id]
    courier_chat_id = state["courier_chat_id"]
    courier_name = state["courier_name"]

    # Получаем номер телефона
    phone = message.text.strip()

    # Простая валидация номера телефона
    import re
    digits = re.sub(r'\D', '', phone)

    if len(digits) < 10 or len(digits) > 15:
        bot.send_message(
            message.chat.id,
            "⚠️ Неверный формат номера. Номер должен содержать 10-15 цифр.\n"
            "Попробуйте ещё раз или отправьте контакт."
        )
        return

    # Приводим к единому формату (с +)
    if not phone.startswith('+'):
        phone = '+' + digits

    # Обновляем номер в БД
    db.update_courier_phone(courier_chat_id, phone)
    db.log_user_action(message.chat.id, f"updated_courier_phone:{courier_name}")

    bot.send_message(
        message.chat.id,
        f"✅ Номер телефона для переводов Доставщика *{courier_name}* обновлён:\n"
        f"`{phone}`",
        parse_mode="Markdown"
    )

    # Очищаем состояние
    admin_state.pop(message.chat.id, None)


@bot.message_handler(content_types=["contact"])
def handle_contact_for_courier_phone(message):
    """Обработка контакта при изменении номера Доставщика."""
    if not is_admin(message.chat.id):
        return

    state = admin_state.get(message.chat.id, {})
    if state.get("action") != "edit_courier_phone":
        # Если не в режиме редактирования номера, пропускаем
        return

    if not message.contact:
        bot.send_message(message.chat.id, "⚠️ Не удалось получить контакт. Попробуйте ещё раз.")
        return

    courier_chat_id = state["courier_chat_id"]
    courier_name = state["courier_name"]
    phone = message.contact.phone_number

    # Приводим к единому формату
    if not phone.startswith('+'):
        phone = '+' + phone

    # Обновляем номер
    db.update_courier_phone(courier_chat_id, phone)
    db.log_user_action(message.chat.id, f"updated_courier_phone_from_contact:{courier_name}")

    bot.send_message(
        message.chat.id,
        f"✅ Номер телефона для переводов Доставщика *{courier_name}* обновлён через контакт:\n"
        f"`{phone}`",
        parse_mode="Markdown"
    )

    # Очищаем состояние
    admin_state.pop(message.chat.id, None)


@bot.callback_query_handler(func=lambda c: c.data == "hire_yes")
def cb_hire_yes(call):
    """Подтверждение найма курьера."""
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    data = hire_state.pop(call.message.chat.id, None)
    if not data:
        bot.edit_message_text(
            "⚠️ Данные устарели. Начните найм заново.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
        )
        bot.answer_callback_query(call.id)
        return

    name = data["name"]
    courier_chat_id = data["chat_id"]
    phone = data.get("phone")

    # Если нет номера телефона, запрашиваем его отдельно
    if not phone:
        admin_state[call.message.chat.id] = {
            "action": "add_courier_phone",
            "name": name,
            "chat_id": courier_chat_id
        }

        bot.edit_message_text(
            f"📋 Данные Доставщика:\n"
            f"• Имя: {name}\n"
            f"• ID: `{courier_chat_id}`\n"
            f"⚠️ Телефон не был указан.\n"
            f"✍️ Введите номер телефона для переводов текстом:\n"
            f"`+79123456789 или без +`\n\n"
            f"Или отправьте контакт (но учтите, что это может быть ваш номер, а не Доставщика!)",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
        return

    # Если номер есть, добавляем курьера
    db.add_courier(name, courier_chat_id, phone)
    db.log_user_action(call.message.chat.id, f"hired_courier:{courier_chat_id}")

    bot.edit_message_text(
        f"✅ Доставщик «{name}» (ID `{courier_chat_id}`) добавлен.\n"
        f"📞 Номер для переводов: `{phone}`\n\n"
        f"⚠️ Напомните Доставщику написать /start боту, если он ещё этого не сделал.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "Доставщик добавлен")

def admin_add_courier_phone(message):
    """Добавить номер телефона при найме курьера."""
    state = admin_state.pop(message.chat.id)
    name = state["name"]
    courier_chat_id = state["chat_id"]

    phone = message.text.strip()

    # Валидация
    import re
    digits = re.sub(r'\D', '', phone)
    if len(digits) < 10 or len(digits) > 15:
        bot.send_message(
            message.chat.id,
            "⚠️ Неверный формат номера. Номер должен содержать 10-15 цифр.\n"
            "Попробуйте ещё раз или отправьте контакт."
        )
        return

    if not phone.startswith('+'):
        phone = '+' + digits

    db.add_courier(name, courier_chat_id, phone)
    db.log_user_action(message.chat.id, f"hired_courier_with_phone:{courier_chat_id}")

    bot.send_message(
        message.chat.id,
        f"✅ Доставщик «{name}» (ID `{courier_chat_id}`) добавлен.\n"
        f"📞 Номер для переводов: `{phone}`\n\n"
        f"⚠️ Напомните Доставщику написать /start боту, если он ещё этого не сделал.",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda c: c.data == "hire_no")
def cb_hire_no(call):
    hire_state.pop(call.message.chat.id, None)
    bot.edit_message_text(
        "❌ Найм отменён.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda m: admin_state.get(m.chat.id) == "awaiting_courier_id")
def admin_hire_courier_id(message):
    if not is_admin(message.chat.id): return
    try:
        chat_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Не число. Отмена.")
        admin_state.pop(message.chat.id, None)
        return
    admin_state[message.chat.id] = ("awaiting_courier_name", chat_id)
    bot.send_message(message.chat.id, "Введите имя Доставщика:")


@bot.message_handler(func=lambda m: isinstance(admin_state.get(m.chat.id), tuple)
                     and admin_state[m.chat.id][0] == "awaiting_courier_name")
def admin_hire_courier_name(message):
    if not is_admin(message.chat.id): return
    _, chat_id = admin_state.pop(message.chat.id)
    name = (message.text or "").strip()
    if not name:
        bot.send_message(message.chat.id, "⚠️ Пустое имя, отмена.")
        return
    db.add_courier(name, chat_id)
    bot.send_message(message.chat.id, f"✅ Доставщик «{name}» (ID `{chat_id}`) добавлен.",
                     parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == B.BTN_FIRE_COURIER)
def admin_fire_courier(message):
    if not is_admin(message.chat.id): return
    couriers = db.get_all_couriers()
    if not couriers:
        bot.send_message(message.chat.id, "Список Доставщиков пуст.")
        return
    markup = InlineKeyboardMarkup()
    for c in couriers:
        markup.add(InlineKeyboardButton(c["name"], callback_data=f"fire_courier|{c['name']}"))
    bot.send_message(message.chat.id, "Кого уволить?", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("fire_courier|"))
def cb_fire_courier(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа"); return
    name = call.data.split("|", 1)[1]
    n = db.delete_courier_by_name(name)
    bot.edit_message_text(
        f"✅ Доставщик «{name}» удалён." if n else f"Доставщик «{name}» не найден.",
        chat_id=call.message.chat.id, message_id=call.message.message_id,
    )


# ─── Найти чат-ID клиента ────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_FIND_CHAT_ID)
def admin_find_chat_id(message):
    if not is_admin(message.chat.id): return
    bot.send_message(message.chat.id, "Введите номер заказа:")
    bot.register_next_step_handler(message, _find_chat_id_do)


def _find_chat_id_do(message):
    if not is_admin(message.chat.id): return
    uid = db.get_user_id_by_order_number((message.text or "").strip())
    if uid:
        bot.send_message(message.chat.id, f"Чат-ID клиента: `{uid}`", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "Заказ не найден.")


# ─── Написать всем курьерам ─────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_MSG_COURIERS)
def admin_msg_couriers(message):
    if not is_admin(message.chat.id): return
    bot.send_message(message.chat.id, "Введите сообщение для всех Доставщиков:")
    bot.register_next_step_handler(message, _msg_couriers_send)


def _msg_couriers_send(message):
    if not is_admin(message.chat.id): return
    text = f"👤 Админ: {message.text}"
    sent = 0
    for cid in db.get_all_courier_chat_ids():
        try:
            bot.send_message(cid, text)
            sent += 1
        except Exception as e:
            logger.warning("Не удалось отправить Доставщику %s: %s", cid, e)
    bot.send_message(message.chat.id, f"Доставлено: {sent}.")


# ─── База пользователей / Заказы / Рассылка ─────────────────────────

# ════════════════════════════════════════════════════════════════════
#  База пользователей: инлайн-список с пагинацией + карточка
# ════════════════════════════════════════════════════════════════════

USERS_PER_PAGE = 5  # сколько пользователей показывать на одной странице

# admin_state[chat_id] для редактирования полей:
#   {"action": "edit_user_field", "target": <uid>, "field": "name"|"phone"|"address"}
#   {"action": "edit_my_field",   "field": "name"|"phone"|"address"}


def _user_role_badge(user_id: int) -> str:
    """Бейдж статуса пользователя для карточки."""
    if is_admin(user_id):
        return "👑 Администратор"
    if is_courier(user_id):
        return "🚴 Доставщик"
    return "👤 Клиент"


def _format_user_card(u: dict, *, for_self: bool) -> str:
    """
    Текст карточки пользователя. for_self=True — заголовок «Мой профиль»,
    иначе — админская карточка.
    """
    header = "👤 *Мой профиль*" if for_self else "👤 *Карточка пользователя*"
    badge = _user_role_badge(u["id"])
    name = u.get("name") or "—"
    phone = u.get("phone") or "—"
    address = u.get("address") or "—"
    return (
        f"{header}\n\n"
        f"*Статус:* {badge}\n"
        f"*ID:* `{u['id']}`\n"
        f"*Имя:* {_md_escape(name)}\n"
        f"*Телефон:* `{_md_escape(phone)}`\n"
        f"*Адрес:* {_md_escape(address)}"
    )


def _md_escape(s) -> str:
    """Лёгкое экранирование для Markdown (legacy parse mode)."""
    if s is None:
        return "—"
    return str(s).replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")


def _build_users_page_markup(page: int) -> tuple[str, InlineKeyboardMarkup]:
    """Собрать текст заголовка и инлайн-разметку для страницы списка."""
    users = db.get_all_users_for_admin()
    total = len(users)
    if total == 0:
        markup = InlineKeyboardMarkup()
        return "👥 Пользователей нет.", markup

    pages = max(1, ceil(total / USERS_PER_PAGE))
    page = max(0, min(page, pages - 1))
    start = page * USERS_PER_PAGE
    chunk = users[start:start + USERS_PER_PAGE]

    markup = InlineKeyboardMarkup(row_width=1)
    for u in chunk:
        label_name = u.get("name") or "(без имени)"
        # Ограничиваем длину, чтобы кнопка не вылезала
        if len(label_name) > 30:
            label_name = label_name[:29] + "…"
        markup.add(
            InlineKeyboardButton(
                f"ID {u['id']} — {label_name}",
                callback_data=f"usr_view|{u['id']}|{page}",
            )
        )

    # Навигационная строка
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("« Назад", callback_data=f"usr_pg|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="usr_pg_noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Вперёд »", callback_data=f"usr_pg|{page + 1}"))
    markup.row(*nav)

    text = f"👥 *База пользователей*\nВсего: {total}. Страница {page + 1} из {pages}."
    return text, markup


def _build_user_card_markup(user_id: int, page: int) -> InlineKeyboardMarkup:
    """Кнопки для админской карточки пользователя."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("✏️ Редактировать", callback_data=f"usr_edit|{user_id}|{page}"),
        InlineKeyboardButton("🗑 Удалить", callback_data=f"usr_del|{user_id}|{page}"),
    )
    markup.row(
        InlineKeyboardButton("<< Назад к списку", callback_data=f"usr_pg|{page}")
    )
    return markup


def _build_user_edit_field_markup(user_id: int, page: int) -> InlineKeyboardMarkup:
    """Кнопки выбора поля для редактирования."""
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("👤 Имя",     callback_data=f"usr_efld|{user_id}|name|{page}"))
    markup.add(InlineKeyboardButton("📞 Телефон", callback_data=f"usr_efld|{user_id}|phone|{page}"))
    markup.add(InlineKeyboardButton("🏠 Адрес",   callback_data=f"usr_efld|{user_id}|address|{page}"))
    markup.add(InlineKeyboardButton("<< Назад",   callback_data=f"usr_view|{user_id}|{page}"))
    return markup


@bot.message_handler(func=lambda m: m.text == B.BTN_USERS_DB)
def admin_users(message):
    """Открыть инлайн-список пользователей (страница 0)."""
    if not is_admin(message.chat.id):
        return
    text, markup = _build_users_page_markup(page=0)
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "usr_pg_noop")
def cb_users_pg_noop(call):
    """Тык по индикатору страницы — ничего не делаем, просто гасим часики."""
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("usr_pg|"))
def cb_users_page(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    try:
        page = int(call.data.split("|", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id)
        return
    text, markup = _build_users_page_markup(page=page)
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=markup,
        )
    except Exception:
        # Если редактировать нельзя (например, после фото) — шлём новое
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("usr_view|"))
def cb_user_view(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    parts = call.data.split("|")
    if len(parts) < 3:
        bot.answer_callback_query(call.id)
        return
    try:
        uid = int(parts[1])
        page = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id)
        return

    u = db.get_user_for_admin(uid)
    if not u:
        bot.answer_callback_query(call.id, "Пользователь не найден", show_alert=True)
        # Освежим список
        text, markup = _build_users_page_markup(page=page)
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                  parse_mode="Markdown", reply_markup=markup)
        except Exception:
            pass
        return

    text = _format_user_card(u, for_self=False)
    markup = _build_user_card_markup(uid, page)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("usr_edit|"))
def cb_user_edit_menu(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    parts = call.data.split("|")
    try:
        uid = int(parts[1])
        page = int(parts[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id)
        return
    markup = _build_user_edit_field_markup(uid, page)
    try:
        bot.edit_message_text(
            f"✏️ Что редактируем у пользователя `{uid}`?",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=markup,
        )
    except Exception:
        bot.send_message(call.message.chat.id,
                         f"✏️ Что редактируем у пользователя `{uid}`?",
                         parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("usr_efld|"))
def cb_user_edit_field(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    parts = call.data.split("|")
    if len(parts) < 4:
        bot.answer_callback_query(call.id)
        return
    try:
        uid = int(parts[1])
        field = parts[2]
        page = int(parts[3])
    except ValueError:
        bot.answer_callback_query(call.id)
        return
    if field not in ("name", "phone", "address"):
        bot.answer_callback_query(call.id, "Неизвестное поле", show_alert=True)
        return

    admin_state[call.message.chat.id] = {
        "action": "edit_user_field",
        "target": uid,
        "field": field,
        "page": page,
    }
    label = {"name": "новое ФИО", "phone": "новый телефон", "address": "новый адрес"}[field]
    bot.send_message(
        call.message.chat.id,
        f"✏️ Введите {label} для пользователя `{uid}`.\n"
        f"Отправьте «отмена», чтобы прервать.",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(
    func=lambda m: isinstance(admin_state.get(m.chat.id), dict)
    and admin_state[m.chat.id].get("action") == "edit_user_field"
)
def admin_users_edit_apply(message):
    state = admin_state.get(message.chat.id, {})
    uid = state.get("target")
    field = state.get("field")
    page = state.get("page", 0)
    value = (message.text or "").strip()

    if value.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Отменено.")
        return

    if not value:
        bot.send_message(message.chat.id, "⚠️ Пустое значение. Введите снова или «отмена».")
        return

    # Базовая валидация телефона
    if field == "phone":
        import re
        digits = re.sub(r"\D", "", value)
        if len(digits) < 10 or len(digits) > 15:
            bot.send_message(message.chat.id, "⚠️ Телефон должен содержать 10–15 цифр. Введите снова или «отмена».")
            return
        if not value.startswith("+"):
            value = "+" + digits

    # Сохраняем (save_user_pii шифрует значения автоматически)
    kwargs = {field: value}
    db.save_user_pii(uid, **kwargs)
    db.log_user_action(message.chat.id, f"admin_edit_user:{uid}:{field}")

    admin_state.pop(message.chat.id, None)

    u = db.get_user_for_admin(uid)
    if not u:
        bot.send_message(message.chat.id, "✅ Сохранено, но запись больше не находится.")
        return

    text = "✅ Сохранено.\n\n" + _format_user_card(u, for_self=False)
    markup = _build_user_card_markup(uid, page)
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("usr_del|"))
def cb_user_delete_confirm(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    parts = call.data.split("|")
    try:
        uid = int(parts[1])
        page = int(parts[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id)
        return

    if is_admin(uid):
        bot.answer_callback_query(
            call.id,
            "Нельзя удалить запись администратора отсюда.",
            show_alert=True,
        )
        return

    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("✅ Да, удалить", callback_data=f"usr_delok|{uid}|{page}"),
        InlineKeyboardButton("⛔ Отмена",     callback_data=f"usr_view|{uid}|{page}"),
    )
    try:
        bot.edit_message_text(
            f"⚠️ Удалить пользователя `{uid}` полностью?\n"
            f"Будут стёрты ФИО, телефон, адрес, согласие и корзина.\n"
            f"Перед следующим заказом пользователю придётся снова заполнить профиль.",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=markup,
        )
    except Exception:
        bot.send_message(call.message.chat.id,
                         f"⚠️ Удалить пользователя `{uid}`?",
                         parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("usr_delok|"))
def cb_user_delete_do(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    parts = call.data.split("|")
    try:
        uid = int(parts[1])
        page = int(parts[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id)
        return

    if is_admin(uid):
        bot.answer_callback_query(call.id, "Нельзя удалить администратора.", show_alert=True)
        return

    rowcount = db.delete_user_completely(uid)
    db.log_user_action(call.message.chat.id, f"admin_delete_user:{uid}")

    text, markup = _build_users_page_markup(page=page)
    note = "✅ Пользователь удалён.\n\n" if rowcount else "ℹ️ Запись уже отсутствовала.\n\n"
    try:
        bot.edit_message_text(note + text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, note + text,
                         parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id, "Удалено")


# ════════════════════════════════════════════════════════════════════
#  Мой профиль (для всех пользователей)
# ════════════════════════════════════════════════════════════════════

def _build_my_profile_markup() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("✏️ Редактировать", callback_data="me_edit"),
        InlineKeyboardButton("🗑 Удалить",       callback_data="me_del"),
    )
    markup.row(InlineKeyboardButton("<< Назад", callback_data="me_back"))
    return markup


def _build_my_profile_edit_markup() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("👤 Имя",     callback_data="me_efld|name"))
    #markup.add(InlineKeyboardButton("📞 Телефон", callback_data="me_efld|phone"))
    markup.add(InlineKeyboardButton("🏠 Адрес",   callback_data="me_efld|address"))
    markup.add(InlineKeyboardButton("<< Назад",   callback_data="me_view"))
    return markup


def _show_my_profile(chat_id: int, *, message_id: Optional[int] = None) -> None:
    pii = db.get_user_pii(chat_id)
    u = {
        "id": chat_id,
        "name": pii["name"],
        "phone": pii["phone"],
        "address": pii["address"],
    }
    if not pii["name"] and not pii["phone"] and not pii["address"]:
        text = (
            "👤 *Мой профиль*\n\n"
            f"*Статус:* {_user_role_badge(chat_id)}\n"
            f"*ID:* `{chat_id}`\n\n"
            f"Профиль ещё не заполнен. Нажмите «{B.BTN_FILL_PROFILE}» в главном меню."
        )
    else:
        text = _format_user_card(u, for_self=True)

    markup = _build_my_profile_markup()
    if message_id is not None:
        try:
            bot.edit_message_text(text, chat_id, message_id,
                                  parse_mode="Markdown", reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text == B.BTN_MY_PROFILE)
def my_profile(message):
    _show_my_profile(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data == "me_view")
def cb_me_view(call):
    _show_my_profile(call.message.chat.id, message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "me_back")
def cb_me_back(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)
    send_main_menu(call.message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data == "me_edit")
def cb_me_edit(call):
    markup = _build_my_profile_edit_markup()
    try:
        bot.edit_message_text(
            "✏️ Что редактируем?",
            call.message.chat.id, call.message.message_id,
            reply_markup=markup,
        )
    except Exception:
        bot.send_message(call.message.chat.id, "✏️ Что редактируем?", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("me_efld|"))
def cb_me_edit_field(call):
    parts = call.data.split("|")
    if len(parts) < 2:
        bot.answer_callback_query(call.id)
        return
    field = parts[1]
    if field not in ("name", "phone", "address"):
        bot.answer_callback_query(call.id, "Неизвестное поле", show_alert=True)
        return

    # Для обычных пользователей перед записью ПДн нужно согласие
    if not is_admin(call.message.chat.id):
        if not require_consent(call.message.chat.id):
            bot.answer_callback_query(call.id)
            return

    admin_state[call.message.chat.id] = {
        "action": "edit_my_field",
        "field": field,
    }
    label = {"name": "новое ФИО", "phone": "новый телефон", "address": "новый адрес"}[field]
    bot.send_message(
        call.message.chat.id,
        f"✏️ Введите {label}.\nОтправьте «отмена», чтобы прервать.",
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(
    func=lambda m: isinstance(admin_state.get(m.chat.id), dict)
    and admin_state[m.chat.id].get("action") == "edit_my_field"
)
def my_profile_edit_apply(message):
    state = admin_state.get(message.chat.id, {})
    field = state.get("field")
    value = (message.text or "").strip()

    if value.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Отменено.")
        _show_my_profile(message.chat.id)
        return

    if not value:
        bot.send_message(message.chat.id, "⚠️ Пустое значение. Введите снова или «отмена».")
        return

    if field == "phone":
        import re
        digits = re.sub(r"\D", "", value)
        if len(digits) < 10 or len(digits) > 15:
            bot.send_message(message.chat.id, "⚠️ Телефон должен содержать 10–15 цифр. Введите снова или «отмена».")
            return
        if not value.startswith("+"):
            value = "+" + digits

    db.save_user_pii(message.chat.id, **{field: value})
    db.log_user_action(message.chat.id, f"profile_self_edit:{field}")
    admin_state.pop(message.chat.id, None)

    bot.send_message(message.chat.id, "✅ Сохранено.")
    _show_my_profile(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data == "me_del")
def cb_me_delete_confirm(call):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("✅ Да, удалить", callback_data="me_delok"),
        InlineKeyboardButton("⛔ Отмена",     callback_data="me_view"),
    )
    text = (
        "⚠️ *Удалить мой профиль?*\n\n"
        "Будут стёрты ФИО, телефон, адрес и согласие на обработку ПДн.\n"
        "Перед следующим заказом нужно будет снова дать согласие "
        "и заполнить профиль."
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "me_delok")
def cb_me_delete_do(call):
    chat_id = call.message.chat.id

    # Админа удалять отсюда не позволяем — он один и опознаётся по ADMIN_CHAT_ID,
    # удаление его записи разломает поведение системы.
    if is_admin(chat_id):
        bot.answer_callback_query(
            call.id,
            "Профиль администратора нельзя удалить через эту кнопку.",
            show_alert=True,
        )
        return

    db.delete_user_completely(chat_id)
    db.log_user_action(chat_id, "profile_self_deleted")

    # Чистим in-memory состояния пользователя, чтобы ничего не пыталось
    # обратиться к уже удалённой записи в users.
    for d in (user_payments, user_threads, support_state, support_continue_state,
              admin_state, admin_edit_state, admin_broadcast_state,
              discount_state, report_state, hire_state, user_last_messages):
        try:
            d.pop(chat_id, None)
        except Exception:
            pass

    try:
        bot.edit_message_text(
            "🗑 Профиль удалён.\n\n"
            "Перед следующим заказом потребуется заново дать согласие и "
            f"заполнить профиль («{B.BTN_FILL_PROFILE}»).",
            chat_id, call.message.message_id,
        )
    except Exception:
        bot.send_message(chat_id, "🗑 Профиль удалён.")
    bot.answer_callback_query(call.id, "Удалено")
    send_main_menu(chat_id)


@bot.message_handler(func=lambda m: m.text == B.BTN_ALL_ORDERS)
def admin_all_orders(message):
    if not is_admin(message.chat.id): return
    orders = db.get_all_orders()
    if not orders:
        bot.send_message(message.chat.id, "Заказов нет.")
        return
    cur = "*📋 Все заказы:*\n\n"
    for o in orders:
        line = (f"`{o['order_number']}` — `ID {o['user_id']}` — "
                f"{o['total_price']} ₽ — {o['status']}\n")
        if len(cur) + len(line) > 3800:
            bot.send_message(message.chat.id, cur, parse_mode="Markdown")
            cur = ""
        cur += line
    if cur:
        bot.send_message(message.chat.id, cur, parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == B.BTN_BROADCAST)
def admin_broadcast_start(message):
    if not is_admin(message.chat.id): return
    admin_broadcast_state[message.chat.id] = "awaiting"
    bot.send_message(message.chat.id, "✉ Введите текст рассылки:")


@bot.message_handler(func=lambda m: admin_broadcast_state.get(m.chat.id) == "awaiting")
def admin_broadcast_do(message):
    if not is_admin(message.chat.id): return
    admin_broadcast_state.pop(message.chat.id)
    text = message.text
    sent = 0
    for uid in db.get_all_user_ids():
        try:
            bot.send_message(uid, text)
            sent += 1
        except Exception:
            continue
    bot.send_message(message.chat.id, f"📢 Рассылка завершена. Доставлено: {sent}.")


# ─── Экспорт меню ───────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_EXPORT_MENU)
def admin_export_menu(message):
    if not is_admin(message.chat.id):
        return

    try:
        menu_data = db.export_menu_to_dict()

        # Используем временный файл
        with temporary_file(prefix="menu_export_", suffix=".json") as tmp_file:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(menu_data, f, ensure_ascii=False, indent=2)

            with open(tmp_file, "rb") as f:
                bot.send_document(
                    message.chat.id,
                    f,
                    caption=f"📋 Экспорт меню от {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            f"Категорий: {len(menu_data['categories'])}\n"
                            f"Блюд: {sum(len(cat['dishes']) for cat in menu_data['categories'])}"
                )

        db.log_user_action(message.chat.id, "menu_exported")

    except Exception as e:
        logger.error(f"Ошибка экспорта меню: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка экспорта: {e}")


# Добавить команду для ручной очистки
@bot.message_handler(commands=["cleanup"])
def cmd_cleanup(message):
    """Ручная очистка временных файлов (только для админа)"""
    if not is_admin(message.chat.id):
        return

    msg = bot.send_message(message.chat.id, "🧹 Очистка временных файлов...")

    try:
        # Удаляем все временные файлы старше 1 минуты
        deleted_count, deleted_size = cleanup_all_temp_files(max_age_minutes=1)

        bot.edit_message_text(
            f"✅ Очистка завершена!\n\n"
            f"🗑 Удалено файлов: {deleted_count}\n"
            f"💾 Освобождено: {deleted_size / 1024:.2f} KB",
            chat_id=message.chat.id,
            message_id=msg.message_id
        )
        db.log_user_action(message.chat.id, "manual_cleanup")
    except Exception as e:
        bot.edit_message_text(
            f"❌ Ошибка при очистке: {e}",
            chat_id=message.chat.id,
            message_id=msg.message_id
        )


# Добавить фоновую очистку
def periodic_cleanup():
    """Фоновый поток для периодической очистки"""
    while True:
        try:
            # Удаляем файлы старше 60 минут
            deleted_count, deleted_size = cleanup_all_temp_files(max_age_minutes=60)
            if deleted_count > 0:
                logger.info(f"Периодическая очистка: удалено {deleted_count} файлов")
        except Exception as e:
            logger.error(f"Ошибка в periodic_cleanup: {e}")

        # Пауза 6 часов
        time.sleep(6 * 3600)


# В конце файла, перед bot.infinity_polling()
cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
cleanup_thread.start()
# ─── Импорт меню ───────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_IMPORT_MENU)
def admin_import_menu_start(message):
    if not is_admin(message.chat.id):
        return

    # Спрашиваем, нужно ли очистить текущее меню
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Да, очистить", callback_data="import_clear_yes"),
        InlineKeyboardButton("❌ Нет, дополнить", callback_data="import_clear_no"),
        InlineKeyboardButton("Отмена", callback_data="import_cancel")
    )

    bot.send_message(
        message.chat.id,
        "⚠️ *Импорт меню*\n\n"
        "Очистить текущее меню перед импортом?\n\n"
        "• «Да, очистить» — удалит все существующие категории и блюда\n"
        "• «Нет, дополнить» — добавит новые и обновит существующие\n\n"
        "📎 *Отправьте JSON-файл* с экспортом меню после выбора опции.",
        parse_mode="Markdown",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("import_"))
def cb_import_option(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    if call.data == "import_cancel":
        bot.edit_message_text(
            "❌ Импорт отменён.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.answer_callback_query(call.id)
        return

    clear_existing = (call.data == "import_clear_yes")

    # Сохраняем настройку в admin_state
    admin_state[call.message.chat.id] = {
        "action": "import_menu",
        "clear_existing": clear_existing
    }

    bot.edit_message_text(
        f"📥 Режим импорта: {'очистить существующее' if clear_existing else 'дополнить существующее'}\n\n"
        "📎 Отправьте JSON-файл с экспортом меню:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(content_types=["document"])
def handle_import_file(message):
    """Обработка загруженного файла для импорта меню."""
    if not is_admin(message.chat.id):
        return

    # Проверяем, ожидаем ли мы файл для импорта
    state = admin_state.get(message.chat.id, {})
    if state.get("action") != "import_menu":
        return

    clear_existing = state.get("clear_existing", True)

    try:
        # Скачиваем файл
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Парсим JSON
        import_data = json.loads(downloaded_file.decode("utf-8"))

        # Проверяем структуру
        if "categories" not in import_data:
            bot.send_message(message.chat.id, "❌ Неверный формат файла: отсутствует раздел 'categories'")
            return

        # Импортируем
        stats = db.import_menu_from_dict(import_data, clear_existing)

        # Формируем отчёт
        report = (
            "📊 *Импорт меню завершён*\n\n"
            f"📁 *Категории:*\n"
            f"   • Создано: {stats['categories_created']}\n"
            f"   • Обновлено: {stats['categories_updated']}\n"
            f"🍽️ *Блюда:*\n"
            f"   • Создано: {stats['dishes_created']}\n"
            f"   • Обновлено: {stats['dishes_updated']}\n"
        )

        if stats["errors"]:
            report += f"\n⚠️ *Ошибки:*\n" + "\n".join(f"   • {e}" for e in stats["errors"][:5])
            if len(stats["errors"]) > 5:
                report += f"\n   • ... и ещё {len(stats['errors']) - 5} ошибок"

        bot.send_message(message.chat.id, report, parse_mode="Markdown")
        db.log_user_action(message.chat.id, f"menu_imported: created={stats['dishes_created']}")

        # Очищаем состояние
        admin_state.pop(message.chat.id, None)

    except json.JSONDecodeError as e:
        bot.send_message(message.chat.id, f"❌ Ошибка парсинга JSON: {e}")
    except Exception as e:
        logger.error(f"Ошибка импорта: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка импорта: {e}")
# ─── Оплата/неоплата заказа курьером ──────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith("order_paid|"))
def cb_order_paid(call):
    """Курьер отметил заказ как оплаченный."""
    order_number = call.data.split("|")[1]
    courier_id = call.message.chat.id

    db.mark_order_paid(order_number, paid=True)

    try:
        bot.edit_message_text(
            f"✅ Заказ `{order_number}` отмечен как оплаченный.",
            chat_id=courier_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, "Отмечено как оплачено")


@bot.callback_query_handler(func=lambda c: c.data.startswith("order_unpaid|"))
def cb_order_unpaid(call):
    """Курьер отметил заказ как НЕ оплаченный."""
    order_number = call.data.split("|")[1]
    courier_id = call.message.chat.id

    db.mark_order_paid(order_number, paid=False)

    try:
        bot.edit_message_text(
            f"❌ Заказ `{order_number}` отмечен как НЕОПЛАЧЕННЫЙ.\n"
            f"Вы можете посмотреть неоплаченные заказы в меню «📋 Неоплаченные заказы».",
            chat_id=courier_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, "Отмечено как неоплачено")
    db.log_user_action(courier_id, f"order_unpaid:{order_number}")


# ─── Просмотр неоплаченных заказов курьером ───────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_UNPAID_ORDERS)
def show_unpaid_orders(message):
    """Показывает неоплаченные заказы курьера."""
    if not is_courier(message.chat.id):
        bot.send_message(message.chat.id, "Эта функция доступна только Доставщикам.")
        return

    courier_chat_id = message.chat.id
    unpaid = db.get_unpaid_orders_for_courier(courier_chat_id)

    if not unpaid:
        bot.send_message(
            message.chat.id,
            "✅ У вас нет неоплаченных заказов!",
        )
        return

    for order in unpaid:
        user_id = order["user_id"]
        pii = db.get_user_pii(user_id)
        client_name = pii["name"] or "—"
        client_phone = pii["phone"] or "—"
        client_address = pii["address"] or "—"

        text = (
            f"📋 *Неоплаченный заказ*\n\n"
            f"🔢 *Номер заказа:* `{order['order_number']}`\n"
            f"💰 *Сумма:* {fmt_money(order['total_price'])} ₽\n"
            f"💳 *Способ оплаты:* {order['payment_method']}\n"
            f"📅 *Доставлен:* {order['delivered_at'] or '—'}\n\n"
            f"👤 *Клиент:* {client_name}\n"
            f"📱 *Телефон:* `{client_phone}`\n"
            f"🏠 *Адрес:* {client_address}\n\n"
        )

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "✅ Отметить как оплачено",
            callback_data=f"mark_paid|{order['order_number']}",
        ))

        try:
            bot.send_message(
                message.chat.id,
                text,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        except Exception:
            # Если ошибка Markdown — отправляем без форматирования
            bot.send_message(
                message.chat.id,
                text.replace("*", "").replace("`", "").replace("_", ""),
                reply_markup=markup,
            )


@bot.callback_query_handler(func=lambda c: c.data.startswith("mark_paid|"))
def cb_mark_paid(call):
    """Курьер отметил неоплаченный заказ как оплаченный (из списка)."""
    order_number = call.data.split("|")[1]
    courier_id = call.message.chat.id

    db.mark_order_paid(order_number, paid=True)
    db.log_user_action(courier_id, f"marked_paid:{order_number}")

    try:
        bot.edit_message_text(
            f"✅ Заказ `{order_number}` отмечен как оплаченный!\n\n"
            f"_Это сообщение можно удалить._",
            chat_id=courier_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, "Отмечено как оплачено!")
# ════════════════════════════════════════════════════════════════════
#  Отчёты (админ и курьер)
# ════════════════════════════════════════════════════════════════════

def _period_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора периода отчёта."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📅 Сегодня", callback_data=f"{prefix}|today"),
        InlineKeyboardButton("📅 Неделя",  callback_data=f"{prefix}|week"),
    )
    markup.add(
        InlineKeyboardButton("📅 Месяц",   callback_data=f"{prefix}|month"),
        InlineKeyboardButton("📅 Период",  callback_data=f"{prefix}|custom"),
    )
    markup.add(InlineKeyboardButton("📅 Всё время", callback_data=f"{prefix}|all"))
    return markup


def _period_range(choice: str) -> tuple[Optional[str], Optional[str]]:
    """Преобразовать выбор кнопки в (date_from, date_to). ISO 'YYYY-MM-DD'."""
    today = datetime.now().date()
    if choice == "today":
        return today.isoformat(), today.isoformat()
    if choice == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if choice == "month":
        return (today - timedelta(days=29)).isoformat(), today.isoformat()
    return None, None  # 'all'


def _parse_custom_period(raw: str) -> Optional[tuple[str, str]]:
    """Распарсить 'YYYY-MM-DD YYYY-MM-DD'."""
    parts = (raw or "").strip().split()
    if len(parts) != 2:
        return None
    try:
        d_from = datetime.strptime(parts[0], "%Y-%m-%d").date().isoformat()
        d_to   = datetime.strptime(parts[1], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    return d_from, d_to


# ─── Админский отчёт ────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_ADMIN_REPORT)
def admin_report_start(message):
    if not is_admin(message.chat.id): return
    bot.send_message(message.chat.id, "📊 За какой период составить отчёт?",
                     reply_markup=_period_keyboard("rep_adm"))


@bot.callback_query_handler(func=lambda c: c.data.startswith("rep_adm|"))
def cb_admin_report(call):
    if not is_admin(call.message.chat.id): return
    choice = call.data.split("|")[1]
    if choice == "custom":
        report_state[call.message.chat.id] = {"kind": "admin"}
        bot.send_message(call.message.chat.id,
                         "Введите начало и конец периода через пробел в формате\n"
                         "`ГГГГ-ММ-ДД ГГГГ-ММ-ДД`\n"
                         "Например: `2026-05-01 2026-05-11`",
                         parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        return
    date_from, date_to = _period_range(choice)
    _send_admin_report(call.message.chat.id, date_from, date_to)
    bot.answer_callback_query(call.id)


def _send_admin_report(chat_id: int, date_from: Optional[str], date_to: Optional[str]):
    stats = db.admin_stats(date_from, date_to)
    period_label = f"{date_from} — {date_to}" if date_from else "за всё время"

    t = stats["totals"]
    text = (
        f"📊 *Отчёт по продажам* ({period_label})\n\n"
        f"📦 Доставлено заказов: *{t['count']}*\n"
        f"💰 Общая выручка: *{fmt_money(t['total'])} ₽*\n"
        f"   💳 переводом: {fmt_money(t['by_card'])} ₽\n"
        f"   💵 наличными: {fmt_money(t['by_cash'])} ₽\n"
    )
    if stats["couriers"]:
        text += "\n*По Доставщикам:*\n"
        for c in stats["couriers"]:
            cname = c["courier_name"] or f"ID {c['courier_id']}"
            text += (f"• {cname}: {c['cnt']} зак., {fmt_money(c['total'])} ₽ "
                     f"(💳 {fmt_money(c['by_card'])} / 💵 {fmt_money(c['by_cash'])})\n")
    bot.send_message(chat_id, text, parse_mode="Markdown")

    # Создаём и отправляем Excel в одном контексте
    try:
        with temporary_file(prefix="admin_report_", suffix=".xlsx") as tmp_file:
            success = _build_admin_excel_to_file(tmp_file, date_from, date_to)
            if success and tmp_file.exists():
                with open(tmp_file, "rb") as f:
                    bot.send_document(chat_id, f, caption="📊 Подробный отчёт в Excel")
            # Файл автоматически удалится после выхода из контекста
    except Exception as e:
        logger.error(f"Ошибка при создании Excel для админа: {e}")
        bot.send_message(chat_id, "⚠️ Не удалось создать Excel-отчёт")


def _build_admin_excel_to_file(filepath: Path, date_from, date_to) -> bool:
    """
    Создаёт Excel отчёт напрямую в указанный файл.
    Возвращает True при успехе, False при ошибке.
    """
    try:
        orders = db.all_delivered_orders(date_from, date_to)
        if not orders:
            return False

        wb = Workbook()
        ws = wb.active
        ws.title = "Заказы"
        ws.append(["№ заказа", "Дата доставки", "Сумма ₽", "Оплата",
                   "ID клиента", "Доставщик"])
        for o in orders:
            ws.append([
                o["order_number"], str(o["delivered_at"]), o["total_price"],
                o["payment_method"] or "—", o["user_id"],
                o["courier_name"] or f"ID {o['courier_id']}",
            ])

        # Авто-ширина для первой таблицы
        for col in ws.columns:
            if col[0].value:
                length = max((len(str(c.value)) for c in col if c.value is not None), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        # Лист «Сводка»
        ws2 = wb.create_sheet("Сводка")
        stats = db.admin_stats(date_from, date_to)
        ws2.append(["Метрика", "Значение"])
        ws2.append(["Заказов", stats["totals"]["count"]])
        ws2.append(["Общая выручка ₽", stats["totals"]["total"]])
        ws2.append(["Переводом ₽", stats["totals"]["by_card"]])
        ws2.append(["Наличными ₽", stats["totals"]["by_cash"]])
        ws2.append([])
        ws2.append(["Доставщик", "Заказов", "Сумма ₽", "Переводом ₽", "Наличными ₽"])
        for c in stats["couriers"]:
            cname = c["courier_name"] or f"ID {c['courier_id']}"
            ws2.append([cname, c["cnt"], c["total"], c["by_card"], c["by_cash"]])

        for col in ws2.columns:
            if col[0].value:
                length = max((len(str(x.value)) for x in col if x.value is not None), default=10)
                ws2.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        wb.save(filepath)
        return True

    except Exception as e:
        logger.error(f"Ошибка создания Excel для админа: {e}")
        return False


def _build_admin_excel(date_from, date_to) -> Optional[Path]:
    """Создаёт Excel отчёт и возвращает путь к временному файлу."""
    orders = db.all_delivered_orders(date_from, date_to)
    if not orders:
        return None

    suffix = f"{date_from}_{date_to}" if date_from else "all"

    with temporary_file(prefix=f"admin_report_{suffix}_", suffix=".xlsx") as tmp_file:
        wb = Workbook()
        ws = wb.active
        ws.title = "Заказы"
        ws.append(["№ заказа", "Дата доставки", "Сумма ₽", "Оплата",
                   "ID клиента", "Доставщик"])
        for o in orders:
            ws.append([
                o["order_number"], str(o["delivered_at"]), o["total_price"],
                o["payment_method"] or "—", o["user_id"],
                o["courier_name"] or f"ID {o['courier_id']}",
            ])

        # Авто-ширина
        for col in ws.columns:
            if col[0].value:  # Проверяем что колонка не пустая
                length = max((len(str(c.value)) for c in col if c.value is not None), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        # Лист «Сводка»
        ws2 = wb.create_sheet("Сводка")
        stats = db.admin_stats(date_from, date_to)
        ws2.append(["Метрика", "Значение"])
        ws2.append(["Заказов", stats["totals"]["count"]])
        ws2.append(["Общая выручка ₽", stats["totals"]["total"]])
        ws2.append(["Переводом ₽", stats["totals"]["by_card"]])
        ws2.append(["Наличными ₽", stats["totals"]["by_cash"]])
        ws2.append([])
        ws2.append(["Доставщик", "Заказов", "Сумма ₽", "Переводом ₽", "Наличными ₽"])
        for c in stats["couriers"]:
            cname = c["courier_name"] or f"ID {c['courier_id']}"
            ws2.append([cname, c["cnt"], c["total"], c["by_card"], c["by_cash"]])

        for col in ws2.columns:
            if col[0].value:
                length = max((len(str(x.value)) for x in col if x.value is not None), default=10)
                ws2.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        wb.save(tmp_file)
        return tmp_file  # Возвращаем Path объект


# ─── Отчёт курьера ──────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == B.BTN_COURIER_REPORT)
def courier_report_start(message):
    if not is_courier(message.chat.id): return
    bot.send_message(message.chat.id, "📊 За какой период составить отчёт?",
                     reply_markup=_period_keyboard("rep_cur"))


@bot.callback_query_handler(func=lambda c: c.data.startswith("rep_cur|"))
def cb_courier_report(call):
    if not is_courier(call.message.chat.id): return
    choice = call.data.split("|")[1]
    if choice == "custom":
        report_state[call.message.chat.id] = {"kind": "courier"}
        bot.send_message(call.message.chat.id,
                         "Введите начало и конец периода через пробел в формате\n"
                         "`ГГГГ-ММ-ДД ГГГГ-ММ-ДД`",
                         parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        return
    date_from, date_to = _period_range(choice)
    _send_courier_report(call.message.chat.id, date_from, date_to)
    bot.answer_callback_query(call.id)


def _send_courier_report(courier_chat_id: int,
                         date_from: Optional[str], date_to: Optional[str]):
    stats = db.courier_stats(courier_chat_id, date_from, date_to)
    rating = db.get_courier_rating(courier_chat_id)
    period_label = f"{date_from} — {date_to}" if date_from else "за всё время"

    text = (
        f"📊 *Ваш отчёт* ({period_label})\n\n"
        f"📦 Доставлено: *{stats['count']}*\n"
        f"💰 Сумма: *{fmt_money(stats['total'])} ₽*\n"
        f"   💳 переводом: {fmt_money(stats['by_card'])} ₽\n"
        f"   💵 наличными: {fmt_money(stats['by_cash'])} ₽\n\n"
        f"⭐ Ваш рейтинг: {fmt_rating(rating['avg'], rating['count'])}"
    )
    bot.send_message(courier_chat_id, text, parse_mode="Markdown")

    # Создаём и отправляем Excel в одном контексте
    try:
        with temporary_file(prefix=f"courier_{courier_chat_id}_", suffix=".xlsx") as tmp_file:
            success = _build_courier_excel_to_file(tmp_file, courier_chat_id, date_from, date_to)
            if success and tmp_file.exists():
                with open(tmp_file, "rb") as f:
                    bot.send_document(courier_chat_id, f, caption="📊 Подробный отчёт в Excel")
            # Файл автоматически удалится после выхода из контекста
    except Exception as e:
        logger.error(f"Ошибка при создании Excel для Доставщика {courier_chat_id}: {e}")
        bot.send_message(courier_chat_id, "⚠️ Не удалось создать Excel-отчёт")


def _build_courier_excel_to_file(filepath: Path, courier_chat_id: int, date_from, date_to) -> bool:
    """
    Создаёт Excel отчёт напрямую в указанный файл.
    Возвращает True при успехе, False при ошибке.
    """
    try:
        orders = db.courier_orders(courier_chat_id, date_from, date_to)
        if not orders:
            return False

        wb = Workbook()
        ws = wb.active
        ws.title = "Заказы"
        ws.append(["№ заказа", "Дата доставки", "Сумма ₽", "Оплата", "ID клиента"])
        for o in orders:
            ws.append([
                o["order_number"], str(o["delivered_at"]), o["total_price"],
                o["payment_method"] or "—", o["user_id"],
            ])

        # Авто-ширина для первой таблицы
        for col in ws.columns:
            if col[0].value:
                length = max((len(str(c.value)) for c in col if c.value is not None), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        # Лист «Сводка»
        ws2 = wb.create_sheet("Сводка")
        stats = db.courier_stats(courier_chat_id, date_from, date_to)
        ws2.append(["Метрика", "Значение"])
        ws2.append(["Заказов", stats["count"]])
        ws2.append(["Сумма ₽", stats["total"]])
        ws2.append(["Переводом ₽", stats["by_card"]])
        ws2.append(["Наличными ₽", stats["by_cash"]])

        for col in ws2.columns:
            if col[0].value:
                length = max((len(str(x.value)) for x in col if x.value is not None), default=10)
                ws2.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        wb.save(filepath)
        return True

    except Exception as e:
        logger.error(f"Ошибка создания Excel для курьера {courier_chat_id}: {e}")
        return False


def _build_courier_excel(courier_chat_id: int, date_from, date_to) -> Optional[Path]:
    orders = db.courier_orders(courier_chat_id, date_from, date_to)
    if not orders:
        return None

    suffix = f"{date_from}_{date_to}" if date_from else "all"

    with temporary_file(prefix=f"courier_{courier_chat_id}_{suffix}_", suffix=".xlsx") as tmp_file:
        wb = Workbook()
        ws = wb.active
        ws.title = "Заказы"
        ws.append(["№ заказа", "Дата доставки", "Сумма ₽", "Оплата", "ID клиента"])
        for o in orders:
            ws.append([
                o["order_number"], str(o["delivered_at"]), o["total_price"],
                o["payment_method"] or "—", o["user_id"],
            ])

        for col in ws.columns:
            if col[0].value:
                length = max((len(str(x.value)) for x in col if x.value is not None), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        ws2 = wb.create_sheet("Сводка")
        stats = db.courier_stats(courier_chat_id, date_from, date_to)
        ws2.append(["Метрика", "Значение"])
        ws2.append(["Заказов", stats["count"]])
        ws2.append(["Сумма ₽", stats["total"]])
        ws2.append(["Переводом ₽", stats["by_card"]])
        ws2.append(["Наличными ₽", stats["by_cash"]])

        for col in ws2.columns:
            if col[0].value:
                length = max((len(str(x.value)) for x in col if x.value is not None), default=10)
                ws2.column_dimensions[col[0].column_letter].width = min(length + 2, 40)

        wb.save(tmp_file)
        return tmp_file


# ─── Произвольный период (ввод дат) ─────────────────────────────────

@bot.message_handler(func=lambda m: m.chat.id in report_state)
def report_custom_period(message):
    state = report_state.pop(message.chat.id)
    parsed = _parse_custom_period(message.text or "")
    if not parsed:
        bot.send_message(message.chat.id,
                         "⚠️ Неверный формат. Пример: `2026-05-01 2026-05-11`",
                         parse_mode="Markdown")
        return
    date_from, date_to = parsed
    if state["kind"] == "admin":
        _send_admin_report(message.chat.id, date_from, date_to)
    else:
        _send_courier_report(message.chat.id, date_from, date_to)


# ─── Команда /v — просмотр действий ─────────────────────────────────

@bot.message_handler(commands=["v"])
def admin_view_log(message):
    """Просмотр лога действий (только для админа)."""
    if not is_admin(message.chat.id):
        return

    try:
        # Парсим лимит из команды, например "/v 50"
        parts = message.text.split()
        if len(parts) > 1:
            limit = int(parts[1])
            if limit < 1 or limit > 100:
                limit = 20
        else:
            limit = 20
    except (IndexError, ValueError):
        limit = 20

    rows = db.get_recent_actions(limit)
    if not rows:
        safe_send_message(message.chat.id, "📋 Лог действий пуст.")
        return

    # Формируем текст (без Markdown для надёжности)
    lines = [f"🕓 Последние {limit} действий:"]
    lines.append("─" * 40)

    for row in rows:
        user_id = row['user_id']
        action = row['action']
        timestamp = row['timestamp']
        lines.append(f"ID: {user_id}")
        lines.append(f"Действие: {action}")
        lines.append(f"Время: {timestamp}")
        lines.append("─" * 40)

    text = "\n".join(lines)

    # Отправляем частями, если текст длинный
    for i in range(0, len(text), 3500):
        chunk = text[i:i + 3500]
        safe_send_message(message.chat.id, chunk, parse_mode=None)

# ════════════════════════════════════════════════════════════════════
#  Запуск
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    db.init_schema()
    logger.info("Бот запускается…")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)