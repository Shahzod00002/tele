"""
bot.py
======
Главный модуль VK-бота кафе «Стамбул». Аналог Telegram-версии, переписан под:
- vk_api (синхронный, аналог pyTelegramBotAPI)
- VK Bots Long Poll API (только сообщества!)
- VK keyboard вместо ReplyKeyboardMarkup и InlineKeyboardMarkup

Что СОХРАНЕНО без изменений (модули):
- db.py            — слой БД
- crypto_utils.py  — шифрование ПДн (Fernet, ФЗ-152)
- utils.py         — временные файлы
- migrations/*     — миграции схемы

Что ИЗМЕНЕНО:
- buttons.py → vk_buttons.py (тексты те же + VK keyboard builder)
- config.py: BOT_TOKEN → VK_TOKEN, ADMIN_CHAT_ID → ADMIN_VK_ID

Что РЕДИЗАЙН (нет аналога в VK):
- Найм курьера: вместо forward контакта — ввод ссылки vk.com/idXXX или ID.
- Заполнение телефона: только ввод текстом, кнопки "Поделиться" нет.
- WebApp/MiniApp поддержки: заменён на FAQ + ссылка на админа.

ВНИМАНИЕ: реализация ведётся по этапам.
Этап 1 (готов): каркас — инициализация vk_api + LongPoll, роутинг, /start,
                главное меню, админ-панель с разделами, callback-события.
Этап 2 (готов): профиль и согласие на ПДн —
                - экран согласия (callback + ссылка на политику)
                - пошаговое заполнение профиля: телефон → адрес → ФИО
                - "Мой профиль": просмотр / редактирование одного поля / удаление
                - "Сменить адрес"
                - валидация телефона, отмена в любой момент
Этап 3 (готов): меню, категории, поиск, фото —
                - "📋 Смотреть меню" → инлайн-категории
                - блюда в категории с пагинацией (4 шт/стр.)
                - экран блюда с фото и кнопкой "В корзину"
                - "🔎 Найти блюдо" → инлайн-результаты
                - VK-attachment для фото вместо Telegram file_id
Этап 4 (готов): корзина, оплата, оформление заказа —
                - add_to_cart, открыть/очистить корзину
                - ➖/➕ количества (по id блюда из меню)
                - выбор оплаты: перевод / наличные
                - подтверждение → запрос комментария → создание заказа
                - отправка заказа курьеру + таймер 5 мин на реассайн
                - отмена заказа клиентом
                - повторить отменённый заказ
                - реассайн следующему по рейтингу, "нет курьеров"
Этап 5 (готов): курьеры —
                - "🚴 Выбрать Доставщика" с рейтингом и пагинацией
                - приём / отклонение / завершение заказа
                - запрос рейтинга 1-5 ⭐ у клиента
                - "✅ Оплачено" / "❌ Не оплачено" после доставки
                - "📋 Неоплаченные заказы" + mark_paid
                - "📞 Мой номер для переводов"
Этап 6 (готов): админка — управление меню —
                - категории: добавить / удалить
                - "🍽️ Добавить блюдо" (FSM: категория → имя → цена)
                - "❌ Удалить блюдо" с пагинацией
                - "🥶 Скрыть / ☀️ Вернуть блюдо" поштучно
                - "🥶 Скрыть всё / ☀️ Показать всё меню"
                - "📜 Список скрытых блюд"
                - "📸 Добавить фото" (через VK photo-attachment)
                - "🗑 Удалить фото"
Этап 7 (готов): админ-курьеры —
                - "➕ Нанять Доставщика": ссылка / ID / forward сообщения
                - "❌ Уволить Доставщика" с подтверждением и пагинацией
                - "📱 Изменить номер Доставщика" (с возможностью стереть)
                - "📋 Список Доставщиков"
                - "🆔 Найти VK-ID" по номеру заказа
                - "📩 Написать Доставщикам" — рассылка
Этап 8 (готов): чаты и поддержка —
                - "📩 Чат с доставщиком": клиент → курьер → ответ
                - "💡 Поддержка": FAQ + ссылка на админа или внутренний канал
                - Общий механизм reply_state для курьера и админа
Этап 9 (готов): мои заказы и история —
                - "📦 Мои заказы": 10 последних + inline-карточки деталей
                - "📜 История заказов": текст / TXT / DOCX (до 1000 шт)
                - Загрузка документов через VkUpload.document_message
Этап 10 (готов): скидки —
                - "🏷 Скидки": список активных + добавить / убрать
                - Добавить: категория → блюдо → тип (%/₽) → значение → срок
                - Защита: процент 1–99, сумма не больше цены блюда
                - Срок: бессрочно / 1 / 3 / 7 дней
                - Убрать: список с пагинацией → клик удаляет
Этап 11 (готов): отчёты, цены, пользователи, заказы, рассылка —
                - "📊 Отчёт по выручке" (админ) + "📊 Мой отчёт" (курьер):
                  периоды + Excel-файл
                - "💰 Редактировать цены": категория → блюдо → новая цена
                - "👥 База пользователей": пагинация / карточка / edit / del
                - "📋 Все заказы": текстом с разбивкой по чанкам
                - "📢 Сделать рассылку": всем пользователям
Этап 12 (готов): экспорт/импорт меню в JSON —
                - "📤 Экспорт меню": JSON-файл через send_document
                - "📥 Импорт меню": выбор режима (очистить/дополнить) →
                  ожидание документа → скачивание по url из VK
                  attachment.doc.url → парс → db.import_menu_from_dict
                - Защита: ≤5 МБ, ext='json', UTF-8

🎉 Порт Telegram→VK завершён. Все 151 хэндлер из исходника реализованы.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Optional, Callable, Any

import requests

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.exceptions import ApiError, VkApiError
from vk_api.upload import VkUpload

import config
import db
import vk_buttons as B


# ════════════════════════════════════════════════════════════════════
#   Логирование
# ════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")


# ════════════════════════════════════════════════════════════════════
#   Инициализация VK API
# ════════════════════════════════════════════════════════════════════
vk_session = vk_api.VkApi(token=config.VK_TOKEN)
vk = vk_session.get_api()                                      # шорткат к методам API
vk_upload = VkUpload(vk_session)                               # для загрузки файлов
longpoll = VkBotLongPoll(vk_session, group_id=config.VK_GROUP_ID)


# ════════════════════════════════════════════════════════════════════
#   In-memory состояния (как в Telegram-версии)
#   ВАЖНО: все ключи — VK user_id (int).
# ════════════════════════════════════════════════════════════════════
user_payments:           dict[int, str]    = {}   # user_id → метод оплаты
admin_state:             dict[int, object] = {}   # user_id → произвольное состояние
admin_edit_state:        dict[int, dict]   = {}   # для редактирования цен
admin_broadcast_state:   dict[int, str]    = {}
user_last_messages:      dict[int, dict]   = {}
discount_state:          dict[int, dict]   = {}
report_state:            dict[int, dict]   = {}
support_state:           dict[int, dict]   = {}
support_reply_state:     dict[int, dict]   = {}
support_continue_state:  dict[int, str]    = {}
user_threads:            dict[int, str]    = {}
hire_state:              dict[int, dict]   = {}

ORDER_TIMEOUT_SEC = 5 * 60
ITEMS_PER_PAGE   = 10
DISHES_PER_PAGE  = 12
ORDERS_PER_PAGE  = 5


# ════════════════════════════════════════════════════════════════════
#   Утилиты отправки и проверки прав
# ════════════════════════════════════════════════════════════════════

def safe_send(peer_id: int,
              text: str,
              keyboard: Optional[str] = None,
              attachment: Optional[str] = None,
              **extra) -> Optional[int]:
    """
    Безопасная обёртка над messages.send.

    Args:
        peer_id    : ID назначения. Для ЛС = user_id. Для беседы = 2000000000 + chat_id.
        text       : текст сообщения (до 4096 символов).
        keyboard   : JSON-строка клавиатуры (Keyboard().dump()). None = без клавы.
        attachment : строка вложений вида "photo123_456,doc1_2".
        **extra    : доп. параметры messages.send (forward_messages и т.д.)

    Returns:
        message_id отправленного сообщения или None при ошибке.
    """
    try:
        params = {
            "peer_id":    peer_id,
            "message":    text,
            "random_id":  random.randint(1, 2**31 - 1),
        }
        if keyboard is not None:
            params["keyboard"] = keyboard
        if attachment is not None:
            params["attachment"] = attachment
        params.update(extra)
        return vk.messages.send(**params)
    except ApiError as e:
        logger.error(f"safe_send: ApiError {e.code} для peer={peer_id}: {e}")
    except VkApiError as e:
        logger.error(f"safe_send: VkApiError для peer={peer_id}: {e}")
    except Exception as e:
        logger.exception(f"safe_send: неожиданная ошибка для peer={peer_id}: {e}")
    return None


def edit_message(peer_id: int, conversation_message_id: int,
                 text: str, keyboard: Optional[str] = None,
                 attachment: Optional[str] = None) -> bool:
    """
    Редактировать ранее отправленное сообщение (аналог edit_message_text Telegram).
    В VK редактировать можно только сообщения от имени сообщества и только в
    течение 24 часов с момента отправки.
    """
    try:
        params = {
            "peer_id": peer_id,
            "conversation_message_id": conversation_message_id,
            "message": text,
            "keep_forward_messages": 1,
            "keep_snippets": 1,
        }
        if keyboard is not None:
            params["keyboard"] = keyboard
        if attachment is not None:
            params["attachment"] = attachment
        vk.messages.edit(**params)
        return True
    except Exception as e:
        logger.error(f"edit_message: {e}")
        return False


def delete_message(peer_id: int, conversation_message_id: int) -> bool:
    """
    Удалить сообщение сообщества (delete_for_all=1). Аналог bot.delete_message
    в Telegram. Работает только в 24-часовом окне.
    """
    try:
        vk.messages.delete(
            peer_id=peer_id,
            cmids=conversation_message_id,
            delete_for_all=1,
        )
        return True
    except Exception as e:
        logger.debug(f"delete_message: {e}")
        return False


def send_document(peer_id: int, file_path: str,
                  title: Optional[str] = None,
                  text: str = "") -> Optional[int]:
    """
    Загрузить файл на сервер VK как документ и прикрепить к сообщению.

    Использует vk_api.upload.VkUpload.document_message, который сам делает
    три шага flow: getMessagesUploadServer → upload → docs.save.

    Returns:
        message_id отправленного сообщения или None при ошибке.
    """
    try:
        # title — отображаемое имя файла; если не задано, берётся имя на диске
        doc = vk_upload.document_message(
            doc=file_path,
            peer_id=peer_id,
            title=title or None,
        )
        # Структура: {"type": "doc", "doc": {"owner_id":..., "id":...}}
        d = doc["doc"]
        attachment = f"doc{d['owner_id']}_{d['id']}"
        return safe_send(peer_id, text, attachment=attachment)
    except Exception:
        logger.exception(f"send_document: ошибка для peer={peer_id} file={file_path}")
        return None


def send_event_answer(event_id: str, user_id: int, peer_id: int,
                      event_data: Optional[dict] = None) -> None:
    """
    Ответ на callback-кнопку (аналог bot.answer_callback_query в Telegram).
    event_data может содержать {"type": "show_snackbar", "text": "..."} и т.д.
    """
    try:
        params = {
            "event_id": event_id,
            "user_id":  user_id,
            "peer_id":  peer_id,
        }
        if event_data is not None:
            params["event_data"] = json.dumps(event_data, ensure_ascii=False)
        vk.messages.sendMessageEventAnswer(**params)
    except Exception as e:
        logger.error(f"send_event_answer: {e}")


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_VK_ID


def is_courier(user_id: int) -> bool:
    """Проверка, является ли пользователь курьером."""
    try:
        return db.get_courier_by_chat_id(user_id) is not None
    except Exception:
        logger.exception("is_courier: ошибка проверки")
        return False


# ════════════════════════════════════════════════════════════════════
#   Главное меню / Админ-панель
#   (аналоги send_main_menu / send_admin_panel из Telegram-версии)
# ════════════════════════════════════════════════════════════════════

def build_main_menu_keyboard(user_id: int) -> str:
    """
    Reply-клавиатура главного меню. Содержимое зависит от роли.

    ВАЖНО: VK на практике отдаёт ошибку 911 уже при ~8 рядах в
    reply-клавиатуре (особенно в мобильном клиенте), поэтому пакуем
    по 2 кнопки в ряд и держимся в пределах 7 рядов. При наличии
    ролей курьера/админа добавляются ещё 1–2 ряда.
    """
    kb = B.Keyboard(one_time=False)

    # Ряд 1: меню + поиск
    kb.row(
        B.text_button(B.BTN_VIEW_MENU,   color=B.COLOR_PRIMARY),
        B.text_button(B.BTN_SEARCH_DISH),
    )
    # Ряд 2: профиль
    kb.row(
        B.text_button(B.BTN_FILL_PROFILE),
        B.text_button(B.BTN_MY_PROFILE),
    )
    # Ряд 3: корзина
    kb.row(
        B.text_button(B.BTN_OPEN_CART,  color=B.COLOR_POSITIVE),
        B.text_button(B.BTN_CLEAR_CART, color=B.COLOR_NEGATIVE),
    )
    # Ряд 4: курьер
    kb.row(
        B.text_button(B.BTN_CHOOSE_COURIER),
        B.text_button(B.BTN_CHAT_COURIER),
    )
    # Ряд 5: заказы
    kb.row(
        B.text_button(B.BTN_MY_ORDERS),
        B.text_button(B.BTN_ORDER_HISTORY),
    )
    # Ряд 6: адрес + поддержка
    kb.row(
        B.text_button(B.BTN_CHANGE_ADDRESS),
        B.text_button(B.BTN_SUPPORT),
    )
    # Базовых рядов = 6. Остаётся бюджет ещё на 1–2 ряда для ролей.

    # Курьер (не админ): 1 плотный ряд из 3 кнопок.
    if is_courier(user_id) and not is_admin(user_id):
        kb.row(
            B.text_button(B.BTN_COURIER_REPORT),
            B.text_button(B.BTN_UNPAID_ORDERS),
            B.text_button(B.BTN_MY_PHONE),
        )
        # Итого: 7 рядов ✓

    # Админ
    if is_admin(user_id):
        if is_courier(user_id):
            # Курьер+админ — самый плотный кейс. Чтобы вместиться в 7 рядов,
            # пакуем 4 курьерско-админских кнопки в 1 ряд по 4 шт.
            # (в ряду допустимо до 5 кнопок).
            kb.row(
                B.text_button(B.BTN_COURIER_REPORT),
                B.text_button(B.BTN_UNPAID_ORDERS),
                B.text_button(B.BTN_MY_PHONE),
                B.text_button(B.BTN_ADMIN_PANEL, color=B.COLOR_PRIMARY),
            )
            # Итого: 7 рядов ✓
        else:
            kb.row(B.text_button(B.BTN_ADMIN_PANEL, color=B.COLOR_PRIMARY))
            # Итого: 7 рядов ✓

    return kb.dump()


def send_main_menu(peer_id: int, user_id: int, greeting: bool = False) -> None:
    text = "Добро пожаловать! Выберите действие:" if greeting else "Главное меню:"
    safe_send(peer_id, text, keyboard=build_main_menu_keyboard(user_id))


def build_admin_panel_keyboard() -> str:
    """
    Главное окно админ-панели. В Telegram-версии тут было ~16 рядов —
    в VK это никак не помещается (лимит ~7–10 рядов, реально ~7).
    Поэтому делим админку на 3 раздела по тематике + общие действия.
    """
    kb = B.Keyboard(one_time=False)
    kb.row(
        B.text_button(B.BTN_ADMIN_MENU_SECTION,    color=B.COLOR_PRIMARY),
        B.text_button(B.BTN_ADMIN_COURIERS_SECTION, color=B.COLOR_PRIMARY),
    )
    kb.row(
        B.text_button(B.BTN_ADMIN_SERVICE_SECTION, color=B.COLOR_PRIMARY),
        B.text_button(B.BTN_ADMIN_REPORT),
    )
    kb.row(
        B.text_button(B.BTN_USERS_DB),
        B.text_button(B.BTN_ALL_ORDERS),
    )
    kb.row(
        B.text_button(B.BTN_BROADCAST),
        B.text_button(B.BTN_FIND_CHAT_ID),
    )
    kb.row(B.text_button(B.BTN_BACK, color=B.COLOR_NEGATIVE))
    return kb.dump()


def build_admin_menu_section_keyboard() -> str:
    """Раздел админки: работа с меню и блюдами."""
    kb = B.Keyboard(one_time=False)
    kb.row(
        B.text_button(B.BTN_ADD_DISH,    color=B.COLOR_POSITIVE),
        B.text_button(B.BTN_DELETE_DISH, color=B.COLOR_NEGATIVE),
    )
    kb.row(
        B.text_button(B.BTN_ADD_PHOTO),
        B.text_button(B.BTN_DELETE_PHOTO),
    )
    kb.row(
        B.text_button(B.BTN_FREEZE_DISH),
        B.text_button(B.BTN_UNFREEZE_DISH),
    )
    kb.row(
        B.text_button(B.BTN_FREEZE_ALL),
        B.text_button(B.BTN_UNFREEZE_ALL),
    )
    kb.row(
        B.text_button(B.BTN_LIST_FROZEN),
        B.text_button(B.BTN_EDIT_PRICES),
    )
    kb.row(
        B.text_button(B.BTN_CATEGORIES),
        B.text_button(B.BTN_DISCOUNTS),
    )
    kb.row(B.text_button(B.BTN_BACK_TO_ADMIN, color=B.COLOR_NEGATIVE))
    return kb.dump()


def build_admin_couriers_section_keyboard() -> str:
    """Раздел админки: курьеры."""
    kb = B.Keyboard(one_time=False)
    kb.row(
        B.text_button(B.BTN_HIRE_COURIER, color=B.COLOR_POSITIVE),
        B.text_button(B.BTN_FIRE_COURIER, color=B.COLOR_NEGATIVE),
    )
    kb.row(
        B.text_button(B.BTN_EDIT_COURIER_PHONE),
        B.text_button(B.BTN_COURIER_LIST),
    )
    kb.row(B.text_button(B.BTN_MSG_COURIERS))
    kb.row(B.text_button(B.BTN_BACK_TO_ADMIN, color=B.COLOR_NEGATIVE))
    return kb.dump()


def build_admin_service_section_keyboard() -> str:
    """Раздел админки: экспорт/импорт меню и сервисные операции."""
    kb = B.Keyboard(one_time=False)
    kb.row(
        B.text_button(B.BTN_EXPORT_MENU),
        B.text_button(B.BTN_IMPORT_MENU),
    )
    kb.row(B.text_button(B.BTN_BACK_TO_ADMIN, color=B.COLOR_NEGATIVE))
    return kb.dump()


def send_admin_panel(peer_id: int, user_id: int) -> None:
    if not is_admin(user_id):
        safe_send(peer_id, "У вас нет доступа к админ-командам.")
        return
    safe_send(peer_id, "⚙️ Админ-панель:", keyboard=build_admin_panel_keyboard())


# ════════════════════════════════════════════════════════════════════
#   РОУТЕРЫ
#
#   В отличие от telebot, в vk_api нет встроенного декоратора-роутера.
#   Поэтому делаем простые dict'ы:
#     - TEXT_HANDLERS: { "точный текст кнопки" → функция(event) }
#     - PAYLOAD_HANDLERS: { "command" → функция(event, payload_dict) }
#     - CALLBACK_HANDLERS: { "command" → функция(event, payload_dict) }
#
#   Функции принимают объект event (vk_api.bot_longpoll.VkBotMessageEvent
#   или MessageEvent). Внутри хэндлера достаётся peer_id, from_id и т.д.
#
#   Также есть STATE_HANDLERS — функции, которые срабатывают если
#   user_id находится в каком-то состоянии (admin_state, hire_state, ...)
# ════════════════════════════════════════════════════════════════════

TEXT_HANDLERS:     dict[str, Callable] = {}
PAYLOAD_HANDLERS:  dict[str, Callable] = {}
CALLBACK_HANDLERS: dict[str, Callable] = {}
STATE_HANDLERS:    list[Callable]      = []  # порядок имеет значение


def on_text(label: str):
    """Регистратор для точного совпадения текста сообщения."""
    def decorator(fn):
        TEXT_HANDLERS[label] = fn
        return fn
    return decorator


def on_payload(cmd: str):
    """Регистратор для пейлоада обычного сообщения (нажатие text-кнопки с payload)."""
    def decorator(fn):
        PAYLOAD_HANDLERS[cmd] = fn
        return fn
    return decorator


def on_callback(cmd: str):
    """Регистратор для callback-кнопок (event message_event)."""
    def decorator(fn):
        CALLBACK_HANDLERS[cmd] = fn
        return fn
    return decorator


def on_state(predicate: Callable[[int, str], bool]):
    """
    Регистратор для произвольных состояний:
      predicate(user_id, text) → bool. Если True — вызываем зарегистрированную
      функцию. Регистрируется парой (predicate, handler).
    """
    def decorator(fn):
        STATE_HANDLERS.append((predicate, fn))
        return fn
    return decorator


# ════════════════════════════════════════════════════════════════════
#   БАЗОВЫЕ ХЭНДЛЕРЫ (этап 1)
# ════════════════════════════════════════════════════════════════════

@on_text("/start")
@on_text("Начать")
@on_text("Start")
def cmd_start(event):
    """Аналог @bot.message_handler(commands=["start"]).

    В VK команды /start как таковой нет, но при первом сообщении сообществу
    приходит payload {"command": "start"} автоматически (если включено в
    настройках сообщества), либо пользователь просто пишет любое сообщение."""
    send_main_menu(event["peer_id"], event["from_id"], greeting=True)


@on_payload("start")
def payload_start(event, payload):
    send_main_menu(event["peer_id"], event["from_id"], greeting=True)


@on_text(B.BTN_BACK)
def go_back(event):
    send_main_menu(event["peer_id"], event["from_id"])


@on_text(B.BTN_ADMIN_PANEL)
def open_admin_panel(event):
    send_admin_panel(event["peer_id"], event["from_id"])


@on_text(B.BTN_BACK_TO_ADMIN)
def back_to_admin(event):
    send_admin_panel(event["peer_id"], event["from_id"])


@on_text(B.BTN_ADMIN_MENU_SECTION)
def open_admin_menu_section(event):
    if not is_admin(event["from_id"]):
        return
    safe_send(event["peer_id"], "🍽️ Меню и блюда:",
              keyboard=build_admin_menu_section_keyboard())


@on_text(B.BTN_ADMIN_COURIERS_SECTION)
def open_admin_couriers_section(event):
    if not is_admin(event["from_id"]):
        return
    safe_send(event["peer_id"], "🚴 Управление курьерами:",
              keyboard=build_admin_couriers_section_keyboard())


@on_text(B.BTN_ADMIN_SERVICE_SECTION)
def open_admin_service_section(event):
    if not is_admin(event["from_id"]):
        return
    safe_send(event["peer_id"], "🔧 Сервисные операции:",
              keyboard=build_admin_service_section_keyboard())


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 2: Профиль и согласие на обработку ПДн (152-ФЗ)
#
#   Логика:
#   - Заполнение профиля идёт по шагам: телефон → адрес → ФИО.
#     В Telegram использовался register_next_step_handler;
#     в VK его нет — храним состояние в profile_state[user_id].
#   - Перед первым сбором ПДн (для НЕ-админа) показываем экран согласия
#     с inline-кнопками "Принимаю / Отказываюсь" (callback-кнопки VK).
#   - Markdown в VK не поддерживается — используем обычный текст + эмодзи.
#   - Системной кнопки "Поделиться телефоном" в VK нет, поэтому номер
#     вводится только текстом, с валидацией по количеству цифр.
# ════════════════════════════════════════════════════════════════════

import re

# Состояния пошагового заполнения профиля.
# profile_state[user_id] = {"step": "phone"|"address"|"name", "phone": ..., "address": ..., "for_admin": bool}
profile_state: dict[int, dict] = {}

# Состояние смены только адреса.
change_address_state: set[int] = set()

# Состояние редактирования одного поля из «Мой профиль».
# my_edit_state[user_id] = {"field": "name"|"phone"|"address"}
my_edit_state: dict[int, dict] = {}


# ─── Хелперы форматирования ─────────────────────────────────────────

def user_role_badge(user_id: int) -> str:
    if is_admin(user_id):
        return "👑 Администратор"
    if is_courier(user_id):
        return "🚴 Доставщик"
    return "👤 Клиент"


def format_user_card(user_id: int, pii: dict, *, for_self: bool) -> str:
    header = "👤 Мой профиль" if for_self else "👤 Карточка пользователя"
    name    = pii.get("name")    or "—"
    phone   = pii.get("phone")   or "—"
    address = pii.get("address") or "—"
    return (
        f"{header}\n\n"
        f"Статус: {user_role_badge(user_id)}\n"
        f"VK ID:  {user_id}\n"
        f"Имя:    {name}\n"
        f"Телефон: {phone}\n"
        f"Адрес:  {address}"
    )


def normalize_phone(raw: str) -> Optional[str]:
    """Простая валидация номера: 10–15 цифр. Возвращает '+XXXXX...' или None."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 10 or len(digits) > 15:
        return None
    return "+" + digits


# ─── Согласие на ПДн ───────────────────────────────────────────────

def build_consent_keyboard() -> str:
    """Inline-клавиатура согласия. Callback-кнопки + ссылка на политику."""
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("✅ Принимаю условия",
                             {"command": "consent_accept"},
                             color=B.COLOR_POSITIVE))
    kb.row(B.callback_button("❌ Отказываюсь",
                             {"command": "consent_decline"},
                             color=B.COLOR_NEGATIVE))
    if config.PRIVACY_POLICY_URL:
        kb.row(B.link_button("📄 Политика конфиденциальности",
                             config.PRIVACY_POLICY_URL))
    return kb.dump()


def request_consent(peer_id: int) -> None:
    text = (
        "🔒 Согласие на обработку персональных данных\n\n"
        "Прежде чем продолжить, нам нужно ваше согласие на обработку "
        "ваших персональных данных (ФИО, телефон, адрес) в соответствии "
        "с Федеральным законом № 152-ФЗ.\n\n"
        f"Версия документа: {config.CONSENT_VERSION}"
    )
    safe_send(peer_id, text, keyboard=build_consent_keyboard())


def require_consent(peer_id: int, user_id: int) -> bool:
    """Если согласие есть → True. Иначе показываем экран согласия и False."""
    try:
        if db.has_valid_consent(user_id, config.CONSENT_VERSION):
            return True
    except Exception:
        logger.exception("require_consent: ошибка проверки has_valid_consent")
        return False
    request_consent(peer_id)
    return False


@on_callback("consent_accept")
def cb_consent_accept(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    db.record_consent(user_id, config.CONSENT_VERSION, "accepted")
    db.log_user_action(user_id, "consent_accepted")
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Согласие зафиксировано"})
    safe_send(peer_id,
              "✅ Спасибо! Согласие зафиксировано.\nТеперь заполним профиль.")
    start_profile_flow(peer_id, user_id, for_admin=False)


@on_callback("consent_decline")
def cb_consent_decline(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    db.record_consent(user_id, config.CONSENT_VERSION, "declined")
    db.log_user_action(user_id, "consent_declined")
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Отказ зафиксирован"})
    safe_send(
        peer_id,
        "❌ Вы отказались от обработки ПДн.\n\n"
        "Смотреть меню можно, но оформить заказ не получится — "
        "для доставки нам нужны адрес и телефон. Изменить решение можно "
        "в любой момент через кнопку «Заполнить профиль».",
    )


# ─── Шаги заполнения профиля ────────────────────────────────────────

def start_profile_flow(peer_id: int, user_id: int, *, for_admin: bool) -> None:
    """Запустить пошаговое заполнение профиля. Начинаем с телефона."""
    profile_state[user_id] = {"step": "phone", "for_admin": for_admin}
    safe_send(
        peer_id,
        "📞 Введите ваш номер телефона.\n"
        "Например: +79991234567\n\n"
        "Отправьте «отмена», чтобы прервать.",
    )


@on_text(B.BTN_FILL_PROFILE)
def start_profile(event):
    peer_id = event["peer_id"]
    user_id = event["from_id"]

    # Для админа — без согласия (он же владелец), но логика та же.
    if is_admin(user_id):
        start_profile_flow(peer_id, user_id, for_admin=True)
        return

    if not require_consent(peer_id, user_id):
        return
    start_profile_flow(peer_id, user_id, for_admin=False)


def _profile_in_progress(user_id: int, _text: str) -> bool:
    return user_id in profile_state


@on_state(_profile_in_progress)
def profile_step_router(event):
    """Маршрут шагов профиля. Срабатывает, если user_id в profile_state."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = profile_state.get(user_id) or {}

    # Универсальная отмена
    if text.lower() in ("отмена", "cancel", "/cancel"):
        profile_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.", keyboard=build_main_menu_keyboard(user_id))
        return

    step = state.get("step")

    if step == "phone":
        phone = normalize_phone(text)
        if phone is None:
            safe_send(peer_id,
                      "⚠️ Неверный формат. Номер должен содержать 10–15 цифр.\n"
                      "Попробуйте ещё раз или отправьте «отмена».")
            return
        state["phone"] = phone
        state["step"]  = "address"
        safe_send(peer_id, "✅ Телефон принят.\n\n🏠 Теперь введите ваш адрес доставки:")
        return

    if step == "address":
        if not text:
            safe_send(peer_id, "⚠️ Адрес не может быть пустым. Введите снова или «отмена».")
            return
        state["address"] = text
        state["step"]    = "name"
        safe_send(peer_id, "✅ Адрес принят.\n\n👤 Теперь введите ФИО (Фамилия Имя Отчество):")
        return

    if step == "name":
        if not text:
            safe_send(peer_id, "⚠️ ФИО не может быть пустым. Введите снова или «отмена».")
            return
        name = text
        phone   = state.get("phone")
        address = state.get("address")
        try:
            db.save_user_pii(user_id, name=name, phone=phone, address=address)
            db.log_user_action(user_id, "profile_filled")
        except Exception:
            logger.exception("profile: ошибка сохранения ПДн")
            safe_send(peer_id, "⚠️ Не удалось сохранить профиль. Попробуйте позже.")
            profile_state.pop(user_id, None)
            return
        profile_state.pop(user_id, None)
        safe_send(
            peer_id,
            f"Спасибо, {name}!\nПрофиль сохранён. "
            f"Откройте «{B.BTN_VIEW_MENU}», чтобы заказать.",
            keyboard=build_main_menu_keyboard(user_id),
        )
        return

    # Неизвестное состояние — выходим из FSM, чтобы пользователь не залип
    profile_state.pop(user_id, None)
    send_main_menu(peer_id, user_id)


# ─── Смена только адреса ────────────────────────────────────────────

@on_text(B.BTN_CHANGE_ADDRESS)
def change_address_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id) and not require_consent(peer_id, user_id):
        return
    change_address_state.add(user_id)
    safe_send(peer_id,
              "🏠 Введите новый адрес доставки.\n"
              "Отправьте «отмена», чтобы прервать.")


def _is_changing_address(user_id: int, _text: str) -> bool:
    return user_id in change_address_state


@on_state(_is_changing_address)
def change_address_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        change_address_state.discard(user_id)
        safe_send(peer_id, "Отменено.")
        return

    if not text:
        safe_send(peer_id, "⚠️ Адрес не может быть пустым. Введите снова или «отмена».")
        return

    try:
        db.update_user_address(user_id, text)
        db.log_user_action(user_id, "address_updated")
    except Exception:
        logger.exception("change_address: ошибка сохранения")
        safe_send(peer_id, "⚠️ Не удалось обновить адрес. Попробуйте позже.")
        change_address_state.discard(user_id)
        return

    change_address_state.discard(user_id)
    safe_send(peer_id, "✅ Адрес обновлён.")


# ─── Мой профиль: просмотр / редактирование / удаление ──────────────

def build_my_profile_keyboard(user_id: int) -> str:
    """Inline-клавиатура карточки профиля."""
    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("✏️ Редактировать",
                          {"command": "me_edit"},
                          color=B.COLOR_PRIMARY),
    )
    # Админа удалять отсюда не позволяем (его роль = ADMIN_VK_ID).
    if not is_admin(user_id):
        kb.row(
            B.callback_button("🗑 Удалить мой профиль",
                              {"command": "me_del_ask"},
                              color=B.COLOR_NEGATIVE),
        )
    return kb.dump()


def build_my_profile_edit_keyboard() -> str:
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("👤 Имя",     {"command": "me_efld", "f": "name"}))
    kb.row(B.callback_button("📞 Телефон", {"command": "me_efld", "f": "phone"}))
    kb.row(B.callback_button("🏠 Адрес",   {"command": "me_efld", "f": "address"}))
    kb.row(B.callback_button("⬅ Назад",    {"command": "me_view"}))
    return kb.dump()


def build_my_profile_delete_confirm_keyboard() -> str:
    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("✅ Да, удалить",
                          {"command": "me_del_yes"},
                          color=B.COLOR_NEGATIVE),
        B.callback_button("⛔ Отмена",
                          {"command": "me_view"},
                          color=B.COLOR_SECONDARY),
    )
    return kb.dump()


def send_my_profile(peer_id: int, user_id: int,
                    *, conversation_message_id: Optional[int] = None) -> None:
    """Отправить или отредактировать карточку профиля."""
    try:
        pii = db.get_user_pii(user_id)
    except Exception:
        logger.exception("send_my_profile: ошибка чтения ПДн")
        safe_send(peer_id, "⚠️ Не удалось загрузить профиль.")
        return

    not_filled = not any((pii.get("name"), pii.get("phone"), pii.get("address")))
    if not_filled:
        text = (
            "👤 Мой профиль\n\n"
            f"Статус: {user_role_badge(user_id)}\n"
            f"VK ID:  {user_id}\n\n"
            f"Профиль ещё не заполнен. Нажмите «{B.BTN_FILL_PROFILE}» в главном меню."
        )
    else:
        text = format_user_card(user_id, pii, for_self=True)

    kb = build_my_profile_keyboard(user_id)

    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb):
            return
    safe_send(peer_id, text, keyboard=kb)


@on_text(B.BTN_MY_PROFILE)
def my_profile(event):
    send_my_profile(event["peer_id"], event["from_id"])


@on_callback("me_view")
def cb_me_view(event, payload):
    cmid = event.get("conversation_message_id")
    send_my_profile(event["peer_id"], event["from_id"],
                    conversation_message_id=cmid)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


@on_callback("me_edit")
def cb_me_edit(event, payload):
    cmid = event.get("conversation_message_id")
    text = "✏️ Что редактируем?"
    kb   = build_my_profile_edit_keyboard()
    if cmid is None or not edit_message(event["peer_id"], cmid, text, keyboard=kb):
        safe_send(event["peer_id"], text, keyboard=kb)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


@on_callback("me_efld")
def cb_me_edit_field(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    field   = payload.get("f")
    if field not in ("name", "phone", "address"):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Неизвестное поле"})
        return

    # Для неадмина — нужно согласие
    if not is_admin(user_id) and not require_consent(peer_id, user_id):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    my_edit_state[user_id] = {"field": field}
    label = {"name": "новое ФИО", "phone": "новый телефон", "address": "новый адрес"}[field]
    safe_send(peer_id,
              f"✏️ Введите {label}.\nОтправьте «отмена», чтобы прервать.")
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_editing_my_field(user_id: int, _text: str) -> bool:
    return user_id in my_edit_state


@on_state(_is_editing_my_field)
def my_edit_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = my_edit_state.get(user_id, {})
    field   = state.get("field")

    if text.lower() in ("отмена", "cancel", "/cancel"):
        my_edit_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        send_my_profile(peer_id, user_id)
        return

    if not text:
        safe_send(peer_id, "⚠️ Пустое значение. Введите снова или «отмена».")
        return

    if field == "phone":
        normalized = normalize_phone(text)
        if normalized is None:
            safe_send(peer_id,
                      "⚠️ Телефон должен содержать 10–15 цифр. "
                      "Введите снова или «отмена».")
            return
        text = normalized

    try:
        db.save_user_pii(user_id, **{field: text})
        db.log_user_action(user_id, f"profile_self_edit:{field}")
    except Exception:
        logger.exception("my_edit_apply: ошибка сохранения")
        safe_send(peer_id, "⚠️ Не удалось сохранить. Попробуйте позже.")
        my_edit_state.pop(user_id, None)
        return

    my_edit_state.pop(user_id, None)
    safe_send(peer_id, "✅ Сохранено.")
    send_my_profile(peer_id, user_id)


@on_callback("me_del_ask")
def cb_me_delete_ask(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if is_admin(user_id):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Профиль администратора нельзя удалить отсюда"})
        return
    cmid = event.get("conversation_message_id")
    text = (
        "⚠️ Удалить мой профиль?\n\n"
        "Будут стёрты ФИО, телефон, адрес и согласие на обработку ПДн.\n"
        "Перед следующим заказом нужно будет снова дать согласие "
        "и заполнить профиль."
    )
    kb = build_my_profile_delete_confirm_keyboard()
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("me_del_yes")
def cb_me_delete_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if is_admin(user_id):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Профиль администратора нельзя удалить"})
        return

    try:
        db.delete_user_completely(user_id)
        db.log_user_action(user_id, "profile_self_deleted")
    except Exception:
        logger.exception("cb_me_delete_do: ошибка удаления")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не удалось удалить"})
        return

    # Подчищаем все in-memory состояния этого пользователя
    for d in (user_payments, user_threads, support_state, support_continue_state,
              admin_state, admin_edit_state, admin_broadcast_state,
              discount_state, report_state, hire_state, user_last_messages,
              profile_state, my_edit_state):
        try:
            d.pop(user_id, None)
        except Exception:
            pass
    change_address_state.discard(user_id)

    cmid = event.get("conversation_message_id")
    text = (
        "🗑 Профиль удалён.\n\n"
        "Перед следующим заказом потребуется заново дать согласие и "
        f"заполнить профиль («{B.BTN_FILL_PROFILE}»)."
    )
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Удалено"})
    send_main_menu(peer_id, user_id)


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 3: МЕНЮ — категории, блюда, фото, поиск
#
#   Логика:
#   - "📋 Смотреть меню" → инлайн-клавиатура с категориями (по 2 в ряд).
#   - Клик по категории → список блюд с пагинацией (4 блюда на страницу
#     из-за лимита inline-клавиатуры VK в 6 рядов).
#   - Блюдо без фото → клик добавляет в корзину напрямую.
#   - Блюдо с фото → клик открывает экран с прикреплённым фото и
#     кнопками "В корзину" / "К списку". Реализация: старое сообщение
#     с inline удаляется, отсылается новое с photo-attachment.
#   - "🔎 Найти блюдо" → FSM: ввод текста → инлайн-список совпадений.
#
#   Отличия от Telegram:
#   - Фото хранится в menu.photo как строка-attachment VK
#     (формат: "photo<owner>_<id>" или "photo<owner>_<id>_<access_key>").
#     Старые Telegram-file_id не сработают.
#   - ITEMS_PER_PAGE_VK = 4 (а не 10), чтобы поместиться в 6 рядов
#     inline-клавиатуры VK.
#   - "Закрыть меню" в VK означает попытку удалить сообщение
#     (delete_for_all=1). Если не получилось — редактируем на "Меню
#     закрыто" без клавиатуры.
# ════════════════════════════════════════════════════════════════════

ITEMS_PER_PAGE_VK = 4   # 4 блюда + ряд навигации + ряд "К категориям" = 6 рядов

# Состояние ввода поискового запроса
# Состояние ввода поискового запроса
search_state: set[int] = set()

# Кэш результатов поиска для пагинации.
# search_results_cache[user_id] = {"query": str, "dish_ids": list[int]}
# Храним только id блюд — при отрисовке цены/скидки актуальные подтягиваем
# из БД (на случай, если за время пагинации цена/скидка поменялась).
search_results_cache: dict[int, dict] = {}

SEARCH_RESULTS_PER_PAGE = 5   # 5 кнопок + 1 ряд навигации = 6 рядов inline


# ─── Утилиты форматирования и валидация VK-attachment фото ──────────

def fmt_money(amount: float) -> str:
    """Аналог из Telegram-версии: '1 234' с неразрывным пробелом тысяч."""
    return f"{amount:,.0f}".replace(",", " ")


def fmt_discount(d) -> str:
    if not d:
        return ""
    if d.get("kind") == "percent":
        return f"(-{d['value']}%)"
    return f"(-{d['value']} ₽)"


# Формат VK photo-attachment: "photo<owner>_<id>[_<access_key>]"
# - owner может быть отрицательным (минус) для сообществ
# - access_key опционален; VK использует разные алфавиты в зависимости от
#   типа фото — могут быть _, -, точки. Поэтому разрешаем все стандартные
#   символы из URL-safe base64.
_VK_PHOTO_RE = re.compile(r"^photo-?\d+_\d+(?:_[A-Za-z0-9_\-]+)?$")


def is_vk_photo_attachment(value) -> bool:
    """Проверка, что строка похожа на attachment VK-фото.
    Старые Telegram-file_id (длинные base64-подобные строки) → False."""
    if not value or not isinstance(value, str):
        return False
    return bool(_VK_PHOTO_RE.match(value))


def get_dish_photo_attachment(dish) -> Optional[str]:
    """Извлечь attachment-строку фото из записи блюда, если она корректна.
    sqlite3.Row или dict — оба варианта поддерживаются."""
    if dish is None:
        return None
    try:
        photo = dish["photo"] if "photo" in dish.keys() else None
    except (AttributeError, TypeError):
        photo = dish.get("photo") if isinstance(dish, dict) else None
    if not photo:
        return None
    if is_vk_photo_attachment(photo):
        return photo
    # Фото есть, но не похоже на VK-attachment — логируем
    # (это может быть старый Telegram file_id или повреждённое значение)
    logger.debug(f"get_dish_photo_attachment: photo не проходит валидацию: {photo!r}")
    return None


# ─── Категории ──────────────────────────────────────────────────────

# Сколько категорий помещается на одну страницу inline-клавиатуры:
# 8 категорий по 2 в ряд = 4 ряда + 1 ряд навигации + 1 ряд закрытия = 6
# (это потолок inline VK).
CATEGORIES_PER_PAGE_VK = 7


def build_categories_keyboard(categories: list, page: int = 0) -> str:
    """Inline-клавиатура категорий с пагинацией. По 2 кнопки в ряду."""
    kb = B.Keyboard(inline=True)

    total_pages = max(1, (len(categories) + CATEGORIES_PER_PAGE_VK - 1)
                         // CATEGORIES_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * CATEGORIES_PER_PAGE_VK
    page_cats = categories[start:start + CATEGORIES_PER_PAGE_VK]

    row: list[dict] = []
    for cat in page_cats:
        row.append(B.callback_button(
            cat["name"][:B.MAX_LABEL_LEN],
            {"command": "show_cat", "c": cat["id"], "p": 0},
            color=B.COLOR_PRIMARY,
        ))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    # Пагинация
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button(
                "◀", {"command": "cats_page", "p": page - 1}))
        nav.append(B.callback_button(
            f"{page + 1}/{total_pages}",
            {"command": "noop"},
            color=B.COLOR_SECONDARY,
        ))
        if page < total_pages - 1:
            nav.append(B.callback_button(
                "▶", {"command": "cats_page", "p": page + 1}))
        kb.row(*nav)

    kb.row(B.callback_button("❌ Закрыть",
                             {"command": "close_menu"},
                             color=B.COLOR_SECONDARY))
    return kb.dump()


@on_text(B.BTN_VIEW_MENU)
def show_menu(event):
    peer_id = event["peer_id"]
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("show_menu: ошибка загрузки категорий")
        safe_send(peer_id, "⚠️ Не удалось загрузить меню. Попробуйте позже.")
        return
    if not categories:
        safe_send(peer_id, "📋 Меню пока пусто.")
        return
    safe_send(peer_id,
              "📋 Меню\n\nВыберите категорию:",
              keyboard=build_categories_keyboard(categories))


@on_callback("close_menu")
def cb_close_menu(event, payload):
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if cmid is not None and not delete_message(peer_id, cmid):
        # Не получилось удалить — заменим текст и снимем клавиатуру
        edit_message(peer_id, cmid, "✅ Меню закрыто.")
    send_event_answer(event["event_id"], event["from_id"], peer_id)


@on_callback("back_to_categories")
def cb_back_to_categories(event, payload):
    """Возврат к списку категорий из списка блюд."""
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("cb_back_to_categories: ошибка БД")
        send_event_answer(event["event_id"], event["from_id"], peer_id)
        return
    text = "📋 Меню\n\nВыберите категорию:"
    kb   = build_categories_keyboard(categories, page=0)
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], event["from_id"], peer_id)


@on_callback("cats_page")
def cb_cats_page(event, payload):
    """Пагинация списка категорий в клиентском меню."""
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("cb_cats_page: ошибка БД")
        send_event_answer(event["event_id"], event["from_id"], peer_id)
        return
    text = "📋 Меню\n\nВыберите категорию:"
    kb   = build_categories_keyboard(categories, page=page)
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], event["from_id"], peer_id)


# ─── Список блюд в категории ────────────────────────────────────────

def _format_dish_label(item) -> str:
    """Метка кнопки блюда — с учётом скидки. Ограничена 40 символами VK."""
    name = item["name"]
    if item.get("discount"):
        label = (f"{name} — {fmt_money(item['original_price'])} → "
                 f"{fmt_money(item['final_price'])} ₽")
    else:
        label = f"{name} — {fmt_money(item['final_price'])} ₽"
    if len(label) > B.MAX_LABEL_LEN:
        # При обрезке стараемся сохранить цену в конце.
        # Берём начало "{name} … {price} ₽".
        suffix = (f" — {fmt_money(item['final_price'])} ₽")
        max_name = B.MAX_LABEL_LEN - len(suffix) - 1
        if max_name > 5:
            label = name[:max_name] + "…" + suffix
        else:
            label = label[:B.MAX_LABEL_LEN]
    return label


def build_category_dishes_keyboard(items: list, category_id: int,
                                   page: int, total_pages: int) -> str:
    """
    Inline-клавиатура страницы с блюдами категории.
    Каждое блюдо — отдельный ряд (1 кнопка). Внизу — ряд пагинации
    и ряд "К категориям".
    Лимит 6 рядов в inline → ITEMS_PER_PAGE_VK = 4.
    """
    kb = B.Keyboard(inline=True)

    for it in items:
        photo_attach = get_dish_photo_attachment(it)
        label = _format_dish_label(it)
        if photo_attach:
            # Префикс 📸 и переход на экран с фото
            kb.row(B.callback_button(
                f"📸 {label}"[:B.MAX_LABEL_LEN],
                {"command": "show_photo", "d": it["id"],
                 "c": category_id, "p": page},
            ))
        else:
            # Прямое добавление в корзину
            kb.row(B.callback_button(
                label,
                {"command": "add_to_cart", "d": it["id"]},
            ))

    # Навигация
    nav: list[dict] = []
    if total_pages > 1:
        if page > 0:
            nav.append(B.callback_button(
                "◀", {"command": "show_cat", "c": category_id, "p": page - 1}))
        nav.append(B.callback_button(
            f"{page + 1}/{total_pages}",
            {"command": "noop"},
            color=B.COLOR_SECONDARY,
        ))
        if page < total_pages - 1:
            nav.append(B.callback_button(
                "▶", {"command": "show_cat", "c": category_id, "p": page + 1}))
        kb.row(*nav)

    kb.row(B.callback_button("⬅ К категориям",
                             {"command": "back_to_categories"},
                             color=B.COLOR_SECONDARY))
    return kb.dump()


@on_callback("show_cat")
def cb_show_category(event, payload):
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], event["from_id"], peer_id)
        return

    try:
        category_name = db.get_category_name(category_id)
        items         = db.get_menu_with_discounts(category_id)
        # ВАЖНО: db.get_menu_with_discounts НЕ возвращает поле photo.
        # Подтягиваем его отдельным запросом и склеиваем по id.
        with db.conn_ctx() as conn:
            c = conn.cursor()
            ids = [it["id"] for it in items]
            if ids:
                placeholders = ",".join("?" * len(ids))
                c.execute(f"SELECT id, photo FROM menu WHERE id IN ({placeholders})",
                          ids)
                photo_map = {r["id"]: r["photo"] for r in c.fetchall()}
            else:
                photo_map = {}
        # Прокидываем photo в каждый словарь
        for it in items:
            it["photo"] = photo_map.get(it["id"])
    except Exception:
        logger.exception("cb_show_category: ошибка БД")
        send_event_answer(event["event_id"], event["from_id"], peer_id,
                          {"type": "show_snackbar", "text": "Ошибка загрузки"})
        return

    # Дополнительно скрываем заморожённые блюда — get_menu_with_discounts
    # уже это делает, но на всякий случай страхуемся.
    items = [it for it in items if not it.get("frozen")]

    if not items:
        send_event_answer(event["event_id"], event["from_id"], peer_id,
                          {"type": "show_snackbar",
                           "text": "В этой категории пока нет блюд"})
        return

    total_pages = max(1, (len(items) + ITEMS_PER_PAGE_VK - 1) // ITEMS_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * ITEMS_PER_PAGE_VK
    page_items = items[start:start + ITEMS_PER_PAGE_VK]

    text = f"📋 {category_name}"
    kb   = build_category_dishes_keyboard(page_items, category_id, page, total_pages)

    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], event["from_id"], peer_id)


@on_callback("noop")
def cb_noop(event, payload):
    """Кнопка-индикатор страницы — ничего не делает."""
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


# ─── Экран блюда с фото ─────────────────────────────────────────────

def build_dish_photo_keyboard(menu_id: int, category_id: int, page: int) -> str:
    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("➕ 🛒 В корзину",
                          {"command": "add_to_cart", "d": menu_id},
                          color=B.COLOR_POSITIVE),
    )
    kb.row(
        B.callback_button("⬅ К списку",
                          {"command": "show_cat", "c": category_id, "p": page},
                          color=B.COLOR_SECONDARY),
    )
    return kb.dump()


@on_callback("show_photo")
def cb_show_photo(event, payload):
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    try:
        menu_id     = int(payload["d"])
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], event["from_id"], peer_id)
        return

    try:
        dish = db.get_menu_item_by_id(menu_id)
    except Exception:
        logger.exception("cb_show_photo: ошибка БД")
        send_event_answer(event["event_id"], event["from_id"], peer_id,
                          {"type": "show_snackbar", "text": "Ошибка загрузки"})
        return

    photo_attach = get_dish_photo_attachment(dish)
    if dish is None or photo_attach is None:
        send_event_answer(event["event_id"], event["from_id"], peer_id,
                          {"type": "show_snackbar", "text": "Фото не найдено"})
        return

    # Считаем актуальную цену со скидкой
    try:
        discount = db.get_discount(menu_id)
        final_price = db.apply_discount(dish["price"], discount)
    except Exception:
        logger.exception("cb_show_photo: ошибка получения скидки")
        discount, final_price = None, dish["price"]

    if discount:
        caption = (f"{dish['name']}\n"
                   f"{fmt_money(dish['price'])} ₽ → {fmt_money(final_price)} ₽")
    else:
        caption = f"{dish['name']}\n{fmt_money(final_price)} ₽"

    # Удаляем старое сообщение со списком (best-effort) и шлём новое с фото
    if cmid is not None:
        delete_message(peer_id, cmid)

    kb = build_dish_photo_keyboard(menu_id, category_id, page)
    sent = safe_send(peer_id, caption, keyboard=kb, attachment=photo_attach)
    if sent is None:
        # Фолбэк: фото по какой-то причине не отправилось (например,
        # attachment стал недействителен) — отправим без фото
        safe_send(peer_id,
                  caption + "\n\n(Фото временно недоступно)",
                  keyboard=kb)

    send_event_answer(event["event_id"], event["from_id"], peer_id)


# ─── Поиск блюда ────────────────────────────────────────────────────

@on_text(B.BTN_SEARCH_DISH)
def search_start(event):
    search_state.add(event["from_id"])
    safe_send(event["peer_id"],
              "🔎 Введите название блюда или его часть.\n"
              "Отправьте «отмена», чтобы прервать.")


def _is_searching(user_id: int, _text: str) -> bool:
    return user_id in search_state


def _render_search_page(peer_id: int, user_id: int, page: int = 0,
                        *, conversation_message_id=None) -> None:
    """Отрисовать одну страницу результатов поиска."""
    cache = search_results_cache.get(user_id)
    if not cache or not cache.get("dish_ids"):
        safe_send(peer_id, "🔍 Поиск устарел. Откройте «🔎 Найти блюдо» заново.")
        return

    dish_ids = cache["dish_ids"]
    query    = cache.get("query", "")

    total_pages = max(1, (len(dish_ids) + SEARCH_RESULTS_PER_PAGE - 1)
                         // SEARCH_RESULTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SEARCH_RESULTS_PER_PAGE
    page_ids = dish_ids[start:start + SEARCH_RESULTS_PER_PAGE]

    kb = B.Keyboard(inline=True)
    for did in page_ids:
        try:
            dish = db.get_menu_item_by_id(did)
            if not dish or dish["frozen"]:
                continue
            discount = db.get_discount(did)
            final    = db.apply_discount(dish["price"], discount)
        except Exception:
            continue
        if discount:
            lbl = (f"{dish['name']} — {fmt_money(dish['price'])} → "
                   f"{fmt_money(final)} ₽")
        else:
            lbl = f"{dish['name']} — {fmt_money(final)} ₽"
        if len(lbl) > B.MAX_LABEL_LEN:
            lbl = lbl[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            lbl,
            {"command": "add_to_cart", "d": did},
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "search_page", "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "search_page", "p": page + 1}))
        kb.row(*nav)

    header = f"🔎 Результаты по «{query}»: {len(dish_ids)} шт."
    if conversation_message_id is not None and edit_message(
            peer_id, conversation_message_id, header, keyboard=kb.dump()):
        return
    safe_send(peer_id, header, keyboard=kb.dump())


@on_state(_is_searching)
def search_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        search_state.discard(user_id)
        safe_send(peer_id, "Отменено.")
        return

    if not text:
        safe_send(peer_id, "⚠️ Пустой запрос. Введите название или «отмена».")
        return

    search_state.discard(user_id)

    try:
        dishes = db.search_menu(text)
    except Exception:
        logger.exception("search_apply: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка поиска. Попробуйте позже.")
        return

    if not dishes:
        safe_send(peer_id, "🔍 Ничего не найдено.")
        return

    # Сохраняем id блюд в кэш — для пагинации
    search_results_cache[user_id] = {
        "query":    text,
        "dish_ids": [d["id"] for d in dishes],
    }
    _render_search_page(peer_id, user_id, page=0)


@on_callback("search_page")
def cb_search_page(event, payload):
    """Смена страницы результатов поиска."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _render_search_page(peer_id, user_id, page=page,
                        conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


# ─── Временная заглушка add_to_cart (полная реализация — на Этапе 4) ──

# ─── Корзина и оформление заказа: подробно в Этапе 4 ───────────────


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 4: КОРЗИНА, ОПЛАТА, ОФОРМЛЕНИЕ ЗАКАЗА
#
#   Поток:
#   1. add_to_cart (callback)   — клик по блюду в меню → +1 шт в корзину
#   2. "🛒 Открыть корзину"     — render_cart с инлайн +/- для каждой позиции
#   3. "🗑 Очистить корзину"    — очистка
#   4. "💳 Выбрать оплату"      — выбор: перевод / наличные
#   5. "✅ Подтвердить заказ"   — проверка профиля и курьера, запрос комментария
#   6. Ввод комментария / "Без комментария" → _finalize_order:
#        - создаём заказ в БД
#        - клиенту отправляем подтверждение с реквизитами/способом
#        - курьеру отсылаем заказ с кнопками "Принять/Отклонить"
#        - запускаем таймер 5 минут на реассайнмент
#   7. "❌ Отменить заказ"      — пока заказ в статусе waiting
#   8. "🛒 Повторить заказ"     — после отмены: тот же товар в корзине →
#                                  новый номер заказа
#   9. _try_reassign            — при таймауте/отказе курьера — следующему
#                                  по рейтингу. Если никого нет — "нет
#                                  доступных Доставщиков".
#
#   Что отличается от Telegram:
#   - В payload передаём id блюда (int) вместо name (часто > 255 байт после JSON).
#   - "Состояние ожидания комментария" — order_state[user_id] dict со step.
#     В Telegram это вшивалось в user_payments — это запутывало.
#     Здесь делаем отдельную структуру.
#   - Markdown отсутствует → форматирование "жирным" недоступно, ровный
#     текст с эмодзи. Номера заказов окружаем символами «…», цены — без spec.
#
#   Часть для КУРЬЕРОВ (приём/отклонение/завершение/рейтинг/неоплаченные)
#   делается на Этапе 5. Сейчас курьеру отправляется сообщение с двумя
#   inline-кнопками (callback "order_accept"/"order_reject") — они зарегист-
#   рируются на Этапе 5; пока что нажатие = "Неизвестная команда".
# ════════════════════════════════════════════════════════════════════

# Структура: order_state[user_id] = {"step": "awaiting_comment", "order_number": "...",
#                                     "payment_method": "...", "courier_id": ...}
order_state: dict[int, dict] = {}

# Метод оплаты, выбранный пользователем (до подтверждения).
# Telegram-версия использовала user_payments — тут разделяем "выбран метод"
# и "идёт оформление". Перенесём имя для ясности.
user_payment_method: dict[int, str] = {}

# Хранилище ID сообщений курьеру (нужно для реассайна и обновлений) и
# ID сообщения клиенту (нужно для обновлений «передан другому» / отмены).
# Эти ID и так сохраняются в БД через set_courier_message_id /
# set_order_message_id, тут только in-memory кэш не нужен.

ORDER_TIMEOUT_SEC = 5 * 60
MAX_COMMENT_LEN   = 500


def generate_order_number() -> str:
    """
    Номер заказа: дата-время + короткий случайный суффикс.
    Случайный хвост нужен, чтобы избежать коллизий, если в одну секунду
    оформляется два заказа (например, клиент быстро повторил отменённый).
    """
    from datetime import datetime as _dt
    import secrets
    return _dt.now().strftime("%d%m%Y-%H%M%S") + "-" + secrets.token_hex(2)


# ─── Базовые операции с корзиной ────────────────────────────────────

@on_callback("add_to_cart")
def cb_add_to_cart(event, payload):
    """Добавить блюдо в корзину (+1 шт) по id."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    try:
        menu_id = int(payload["d"])
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        dish = db.get_menu_item_by_id(menu_id)
        if dish is None or dish["frozen"]:
            send_event_answer(event["event_id"], user_id, peer_id,
                              {"type": "show_snackbar",
                               "text": "Блюдо больше не доступно"})
            return
        discount = db.get_discount(menu_id)
        price    = db.apply_discount(dish["price"], discount)
        db.add_to_cart(user_id, dish["name"], price, 1)
    except Exception:
        logger.exception("cb_add_to_cart: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не удалось добавить"})
        return

    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar",
                       "text": f"✓ {dish['name']} добавлено в корзину"})


# ─── Отображение корзины ─────────────────────────────────────────────

def render_cart_text(user_id: int) -> tuple[str, float, list]:
    """
    Собрать текст корзины. Возвращает (text, total, items).
    items — список из БД (для последующей сборки клавиатуры).
    """
    items = db.get_cart(user_id)
    if not items:
        return "🛒 Ваша корзина пуста.", 0.0, []

    lines = []
    total = 0.0
    for it in items:
        qty = it["quantity"]
        subtotal = it["price"] * qty
        total += subtotal
        if qty > 1:
            lines.append(
                f"• {it['dish_name']} — {qty} шт × {fmt_money(it['price'])} ₽ "
                f"= {fmt_money(subtotal)} ₽"
            )
        else:
            lines.append(f"• {it['dish_name']} — {fmt_money(it['price'])} ₽")

    text = ("🛒 Ваша корзина:\n" + "\n".join(lines) +
            f"\n\n💰 Итого: {fmt_money(total)} ₽")
    return text, total, items


CART_ITEMS_PER_PAGE = 3   # 3 ряда +/- + 1 ряд пагинации + 1 оплата + 1 подтверждение = 6


def build_cart_keyboard(user_id: int, items: list, page: int = 0) -> str:
    """
    Inline-клавиатура корзины с пагинацией: для каждой позиции ➖/➕
    (одной строкой), внизу — навигация, "Выбрать оплату" и
    (если метод выбран) "Подтвердить заказ".

    Лимит inline в VK — 6 рядов. CART_ITEMS_PER_PAGE = 3 позиции на стр.
    """
    kb = B.Keyboard(inline=True)

    total_pages = max(1, (len(items) + CART_ITEMS_PER_PAGE - 1)
                         // CART_ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * CART_ITEMS_PER_PAGE
    page_items = items[start:start + CART_ITEMS_PER_PAGE]

    # ID блюда из меню — для +/- (имя может быть длинной кириллицей > 255 байт)
    name_to_menu_id: dict[str, int] = {}
    for it in page_items:
        try:
            row = db.search_menu(it["dish_name"])
            if row:
                name_to_menu_id[it["dish_name"]] = row[0]["id"]
        except Exception:
            pass

    for it in page_items:
        dish_name = it["dish_name"]
        short = dish_name if len(dish_name) <= 18 else dish_name[:17] + "…"
        menu_id = name_to_menu_id.get(dish_name)
        if menu_id is not None:
            kb.row(
                B.callback_button(
                    f"➖ {short}",
                    {"command": "cart_decr", "d": menu_id, "p": page},
                    color=B.COLOR_NEGATIVE,
                ),
                B.callback_button(
                    f"➕ {short}",
                    {"command": "cart_incr", "d": menu_id, "p": page},
                    color=B.COLOR_POSITIVE,
                ),
            )

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button(
                "◀", {"command": "cart_page", "p": page - 1}))
        nav.append(B.callback_button(
            f"{page + 1}/{total_pages}",
            {"command": "noop"},
            color=B.COLOR_SECONDARY,
        ))
        if page < total_pages - 1:
            nav.append(B.callback_button(
                "▶", {"command": "cart_page", "p": page + 1}))
        kb.row(*nav)

    # Способ оплаты + подтверждение
    kb.row(B.callback_button("💳 Выбрать оплату",
                             {"command": "show_payment"},
                             color=B.COLOR_PRIMARY))

    if user_id in user_payment_method:
        kb.row(B.callback_button("✅ Подтвердить заказ",
                                 {"command": "confirm_order"},
                                 color=B.COLOR_POSITIVE))

    return kb.dump()


def send_cart(peer_id: int, user_id: int,
              *, conversation_message_id: Optional[int] = None,
              page: int = 0) -> None:
    """Отправить или отредактировать карточку корзины."""
    text, total, items = render_cart_text(user_id)

    if not items:
        kb = None
    else:
        kb = build_cart_keyboard(user_id, items, page=page)

    if conversation_message_id is not None and kb is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb):
            return
    safe_send(peer_id, text, keyboard=kb)


@on_text(B.BTN_OPEN_CART)
def open_cart(event):
    send_cart(event["peer_id"], event["from_id"])


@on_text(B.BTN_CLEAR_CART)
def clear_cart_handler(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    try:
        db.clear_cart(user_id)
    except Exception:
        logger.exception("clear_cart_handler: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось очистить корзину.")
        return
    user_payment_method.pop(user_id, None)
    safe_send(peer_id, "🗑 Корзина очищена.")


@on_callback("cart_page")
def cb_cart_page(event, payload):
    """Смена страницы в корзине."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    send_cart(peer_id, user_id, conversation_message_id=cmid, page=page)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("cart_incr")
def cb_cart_incr(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        menu_id = int(payload["d"])
        page    = int(payload.get("p", 0))
        dish = db.get_menu_item_by_id(menu_id)
        if not dish:
            send_event_answer(event["event_id"], user_id, peer_id,
                              {"type": "show_snackbar",
                               "text": "Блюдо не найдено"})
            return
        discount = db.get_discount(menu_id)
        price    = db.apply_discount(dish["price"], discount)
        db.add_to_cart(user_id, dish["name"], price, 1)
    except Exception:
        logger.exception("cb_cart_incr: ошибка")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка"})
        return

    send_cart(peer_id, user_id, conversation_message_id=cmid, page=page)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("cart_decr")
def cb_cart_decr(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        menu_id = int(payload["d"])
        page    = int(payload.get("p", 0))
        dish = db.get_menu_item_by_id(menu_id)
        if not dish:
            send_event_answer(event["event_id"], user_id, peer_id,
                              {"type": "show_snackbar",
                               "text": "Блюдо не найдено"})
            return
        db.remove_from_cart(user_id, dish["name"], 1)
    except Exception:
        logger.exception("cb_cart_decr: ошибка")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка"})
        return

    send_cart(peer_id, user_id, conversation_message_id=cmid, page=page)
    send_event_answer(event["event_id"], user_id, peer_id)


# ─── Выбор способа оплаты ───────────────────────────────────────────

def build_payment_options_keyboard() -> str:
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("💳 Перевод",
                             {"command": "pay_select", "m": "card"},
                             color=B.COLOR_PRIMARY))
    kb.row(B.callback_button("💵 Наличными",
                             {"command": "pay_select", "m": "cash"},
                             color=B.COLOR_PRIMARY))
    kb.row(B.callback_button("⬅ Назад в корзину",
                             {"command": "back_to_cart"},
                             color=B.COLOR_SECONDARY))
    return kb.dump()


@on_callback("show_payment")
def cb_show_payment(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    try:
        items = db.get_cart(user_id)
    except Exception:
        logger.exception("cb_show_payment: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if not items:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Корзина пуста"})
        return

    total = sum(it["price"] * it["quantity"] for it in items)
    text  = f"🛒 Сумма заказа: {fmt_money(total)} ₽\n\n💳 Выберите способ оплаты:"
    kb    = build_payment_options_keyboard()

    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id)


_PAYMENT_LABELS = {"card": "Перевод 💳", "cash": "Наличными 💵"}


@on_callback("pay_select")
def cb_pay_select(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    method = payload.get("m")
    if method not in _PAYMENT_LABELS:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    label = _PAYMENT_LABELS[method]
    user_payment_method[user_id] = label

    try:
        items = db.get_cart(user_id)
    except Exception:
        logger.exception("cb_pay_select: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    total = sum(it["price"] * it["quantity"] for it in items) if items else 0.0
    text  = (
        f"Способ оплаты: {label}\n"
        f"Сумма заказа: {fmt_money(total)} ₽\n\n"
        "Нажмите «Подтвердить заказ» ниже 👇"
    )
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("✅ Подтвердить заказ",
                             {"command": "confirm_order"},
                             color=B.COLOR_POSITIVE))
    kb.row(B.callback_button("⬅ Назад в корзину",
                             {"command": "back_to_cart"},
                             color=B.COLOR_SECONDARY))

    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("back_to_cart")
def cb_back_to_cart(event, payload):
    cmid = event.get("conversation_message_id")
    send_cart(event["peer_id"], event["from_id"],
              conversation_message_id=cmid)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


# ─── Подтверждение → запрос комментария → finalize ──────────────────

@on_callback("confirm_order")
def cb_confirm_order(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]

    if not is_admin(user_id) and not require_consent(peer_id, user_id):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Нужно согласие на ПДн"})
        return

    if user_id not in user_payment_method:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Сначала выберите способ оплаты"})
        return

    try:
        phone, address = db.get_user_contact_info(user_id)
    except Exception:
        logger.exception("cb_confirm_order: ошибка БД (профиль)")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not phone or not address:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Сначала заполните профиль"})
        return

    try:
        cart_items = db.get_cart(user_id)
    except Exception:
        logger.exception("cb_confirm_order: ошибка БД (корзина)")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not cart_items:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Корзина пуста"})
        return

    try:
        courier_id = db.get_user_preferred_courier(user_id)
    except Exception:
        logger.exception("cb_confirm_order: ошибка БД (курьер)")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not courier_id:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Сначала выберите Доставщика (🚴)"})
        return

    order_number = generate_order_number()
    order_state[user_id] = {
        "step":           "awaiting_comment",
        "payment_method": user_payment_method[user_id],
        "order_number":   order_number,
        "courier_id":     courier_id,
    }

    # Снимаем выбранный метод (он уже зафиксирован в order_state)
    user_payment_method.pop(user_id, None)

    # Удалим экран корзины и пришлём запрос комментария
    cmid = event.get("conversation_message_id")
    if cmid is not None:
        delete_message(peer_id, cmid)

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("Без комментария ▶",
                             {"command": "skip_comment"},
                             color=B.COLOR_SECONDARY))
    safe_send(peer_id,
              "📝 Комментарий к заказу\n\n"
              "Напишите комментарий (например, особенности доставки, "
              "этаж, домофон).\n\n"
              "Или нажмите кнопку ниже, чтобы пропустить.",
              keyboard=kb.dump())

    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("skip_comment")
def cb_skip_comment(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    if user_id not in order_state:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if cmid is not None:
        delete_message(peer_id, cmid)

    _finalize_order(peer_id, user_id, comment=None)
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_awaiting_comment(user_id: int, _text: str) -> bool:
    state = order_state.get(user_id)
    return bool(state and state.get("step") == "awaiting_comment")


@on_state(_is_awaiting_comment)
def receive_comment(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    comment = (event["text"] or "").strip()

    if len(comment) > MAX_COMMENT_LEN:
        safe_send(peer_id,
                  f"⚠️ Комментарий слишком длинный (макс. {MAX_COMMENT_LEN} символов). "
                  f"Попробуйте короче или нажмите «Без комментария».")
        return

    _finalize_order(peer_id, user_id, comment=comment or None)


# ─── Создание заказа ─────────────────────────────────────────────────

def _finalize_order(peer_id: int, user_id: int, *, comment: Optional[str]) -> None:
    """Создать заказ, сообщить клиенту, отправить курьеру, запустить таймер."""
    state = order_state.get(user_id) or {}
    payment_method = state.get("payment_method")
    order_number   = state.get("order_number")
    courier_id     = state.get("courier_id")

    if not all([payment_method, order_number, courier_id]):
        logger.warning("_finalize_order: неполное состояние для %s: %s", user_id, state)
        order_state.pop(user_id, None)
        safe_send(peer_id, "⚠️ Ошибка оформления, попробуйте заново.")
        return

    try:
        cart_items = db.get_cart(user_id)
    except Exception:
        logger.exception("_finalize_order: ошибка БД (корзина)")
        return

    if not cart_items:
        safe_send(peer_id, "⚠️ Корзина оказалась пустой. Заказ не создан.")
        order_state.pop(user_id, None)
        return

    # Считаем сумму + собираем состав
    total = 0.0
    items_text_lines = []
    for it in cart_items:
        qty = it["quantity"]
        subtotal = it["price"] * qty
        total += subtotal
        if qty > 1:
            items_text_lines.append(
                f"• {it['dish_name']} — {qty} шт × {fmt_money(it['price'])} ₽ "
                f"= {fmt_money(subtotal)} ₽"
            )
        else:
            items_text_lines.append(f"• {it['dish_name']} — {fmt_money(it['price'])} ₽")
    items_text = "\n".join(items_text_lines)

    try:
        db.create_order(user_id, order_number, total,
                        payment_method, courier_id, comment)
    except Exception:
        logger.exception("_finalize_order: ошибка create_order")
        safe_send(peer_id, "⚠️ Не удалось создать заказ. Попробуйте позже.")
        order_state.pop(user_id, None)
        return

    # Текст для клиента
    if payment_method.startswith("Перевод"):
        try:
            courier = db.get_courier_by_chat_id(courier_id)
            pay_phone = (courier["payment_phone"]
                         if courier and courier["payment_phone"]
                         else "не указан, уточните у Доставщика")
        except Exception:
            pay_phone = "не указан, уточните у Доставщика"

        client_text = (
            f"🥘 Ваш заказ: {order_number}\n"
            f"Состав:\n{items_text}\n\n"
            f"💳 Способ оплаты: перевод\n\n"
            f"📱 Телефон для перевода: {pay_phone}\n"
            f"💰 Сумма: {fmt_money(total)} ₽\n\n"
            f"⚠️ В комментарии к переводу обязательно укажите номер заказа "
            f"{order_number}.\n\n"
            f"Ищем доставщика…"
        )
    else:
        client_text = (
            f"🥘 Ваш заказ: {order_number}\n"
            f"Состав:\n{items_text}\n\n"
            f"💵 Способ оплаты: наличными\n"
            f"Сумма: {fmt_money(total)} ₽\n\n"
            f"Передайте сумму Доставщику при получении.\n\n"
            f"Ищем доставщика…"
        )

    if comment:
        client_text += f"\n\n📝 Комментарий: {comment}"

    # Кнопка отмены заказа (пока заказ не принят)
    kb_client = B.Keyboard(inline=True)
    kb_client.row(B.callback_button(
        "❌ Отменить заказ",
        {"command": "cancel_order", "o": order_number},
        color=B.COLOR_NEGATIVE,
    ))
    client_cmid = safe_send(peer_id, client_text, keyboard=kb_client.dump())
    if client_cmid is not None:
        try:
            db.set_order_message_id(order_number, client_cmid)
        except Exception:
            logger.exception("_finalize_order: set_order_message_id")

    # Чистим in-memory state — клиент в активной фазе ожидания
    order_state.pop(user_id, None)

    # Уведомляем курьера и запускаем таймер
    _send_order_to_courier(order_number, courier_id)


def _build_courier_order_text(order_number: str,
                              *, status_prefix: Optional[str] = None) -> str:
    """
    Сформировать унифицированный текст заказа для курьера.

    Содержит: заголовок (с опциональным префиксом статуса), данные клиента,
    сумму, способ оплаты, комментарий и состав. Используется и при первой
    отправке заказа курьеру, и при редактировании после accept/reject/timeout —
    чтобы курьер не терял детали заказа.
    """
    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("_build_courier_order_text: get_order")
        return f"Заказ {order_number}: ошибка загрузки данных."
    if not order:
        return f"Заказ {order_number}: не найден."

    user_id = order["user_id"]
    try:
        pii = db.get_user_pii(user_id)
        name    = pii["name"]    or "—"
        phone   = pii["phone"]   or "—"
        address = pii["address"] or "—"
    except Exception:
        name, phone, address = "—", "—", "—"

    # Корзина клиента — она ещё цела между accept и complete; чистится в complete.
    items_text = ""
    order_total = order["total_price"] if order["total_price"] is not None else 0.0
    try:
        cart_items = db.get_cart(user_id)
    except Exception:
        cart_items = []
    if cart_items:
        lines = []
        recalc_total = 0.0
        for it in cart_items:
            qty = it["quantity"]
            subtotal = it["price"] * qty
            recalc_total += subtotal
            if qty > 1:
                lines.append(
                    f"• {it['dish_name']} — {qty} шт × {fmt_money(it['price'])} ₽ "
                    f"= {fmt_money(subtotal)} ₽"
                )
            else:
                lines.append(f"• {it['dish_name']} — {fmt_money(it['price'])} ₽")
        items_text = "\nСостав:\n" + "\n".join(lines)
        # Если в корзине есть позиции — сумма по корзине надёжнее, чем в БД
        # (на случай, если total_price округлился).
        if recalc_total > 0:
            order_total = recalc_total

    try:
        comment = order["comment"]
    except (KeyError, IndexError, TypeError):
        comment = None

    header = f"Заказ: {order_number}"
    if status_prefix:
        header = f"{status_prefix}\n" + header

    text = (
        f"{header}\n"
        f"Имя:    {name}\n"
        f"Адрес:  {address}\n"
        f"Телефон: {phone}\n"
        f"Сумма:  {fmt_money(order_total)} ₽\n"
        f"Оплата: {order['payment_method']}"
    )
    if comment:
        text += f"\n📝 Комментарий: {comment}"
    text += items_text
    return text


def _send_order_to_courier(order_number: str, courier_id: int) -> None:
    """Отправить заказ курьеру + запустить 5-минутный таймер на реассайн."""
    text = _build_courier_order_text(order_number,
                                     status_prefix="🆕 НОВЫЙ ЗАКАЗ")
    text += (
        f"\n\n⏱ У вас 5 минут на принятие заказа.\n"
        f"ℹ️ Пользователь может отменить заказ до его принятия."
    )

    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("✅ Принять",
                          {"command": "order_accept", "o": order_number},
                          color=B.COLOR_POSITIVE),
        B.callback_button("❌ Отклонить",
                          {"command": "order_reject", "o": order_number},
                          color=B.COLOR_NEGATIVE),
    )

    msg_cmid = safe_send(courier_id, text, keyboard=kb.dump())
    if msg_cmid is None:
        logger.error("Не удалось отправить заказ Доставщику %s", courier_id)
        _try_reassign(order_number, fail_reason="недоступен")
        return

    try:
        db.set_courier_message_id(order_number, msg_cmid)
    except Exception:
        logger.exception("_send_order_to_courier: set_courier_message_id")

    logger.info("Таймер реассайна для %s: %s сек", order_number, ORDER_TIMEOUT_SEC)
    import threading
    t = threading.Timer(ORDER_TIMEOUT_SEC, _on_order_timeout, args=(order_number,))
    t.daemon = True
    t.start()


def _on_order_timeout(order_number: str) -> None:
    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("_on_order_timeout: ошибка get_order")
        return
    if not order:
        return
    status = order["status"] or "waiting"
    if status != "waiting":
        logger.info("Таймаут %s: статус %s — пропуск", order_number, status)
        return

    logger.info("Таймаут заказа %s — реассайн", order_number)
    current_courier = order["courier_id"]
    if current_courier:
        try:
            db.add_rejected_courier(order_number, current_courier)
        except Exception:
            logger.exception("_on_order_timeout: add_rejected_courier")
    _try_reassign(order_number, fail_reason="не успел принять")


def _try_reassign(order_number: str, fail_reason: str) -> None:
    """Передать заказ следующему курьеру по рейтингу."""
    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("_try_reassign: ошибка get_order")
        return
    if not order:
        return

    user_id         = order["user_id"]
    current_courier = order["courier_id"]
    courier_msg_id  = order["courier_msg_id"]

    # Обновим текст у текущего курьера
    if courier_msg_id and current_courier:
        edit_message(
            current_courier, courier_msg_id,
            f"⌛ Заказ {order_number} передан другому Доставщику "
            f"({fail_reason}).",
        )

    try:
        all_couriers = db.get_all_courier_chat_ids()
        rejected     = db.get_rejected_couriers(order_number)
    except Exception:
        logger.exception("_try_reassign: ошибка БД (списки курьеров)")
        return

    exclude = list(set(rejected + ([current_courier] if current_courier else [])))
    available = [c for c in all_couriers if c not in exclude]

    if not available:
        # Все отказались / нет курьеров — отменяем
        try:
            db.update_order_status(order_number, "Отменён (нет Доставщиков)")
        except Exception:
            logger.exception("_try_reassign: ошибка update_order_status")

        kb = B.Keyboard(inline=True)
        kb.row(B.callback_button("🛒 Повторить заказ",
                                 {"command": "repeat_order", "o": order_number},
                                 color=B.COLOR_PRIMARY))
        kb.row(B.callback_button("🗑 Очистить корзину",
                                 {"command": "clear_cart_after_cancel"},
                                 color=B.COLOR_NEGATIVE))

        text = (
            f"❌ Заказ {order_number} отменён.\n"
            f"😞 Сейчас нет доступных Доставщиков.\n\n"
            f"Вы можете повторить заказ или очистить корзину."
        )
        if order["message_id"]:
            if not edit_message(user_id, order["message_id"], text, keyboard=kb.dump()):
                safe_send(user_id, text, keyboard=kb.dump())
        else:
            safe_send(user_id, text, keyboard=kb.dump())
        return

    try:
        next_id = db.next_courier_for_reassign(exclude)
    except Exception:
        logger.exception("_try_reassign: ошибка next_courier_for_reassign")
        return

    if not next_id:
        logger.error("Не найден следующий Доставщик для %s", order_number)
        return

    try:
        db.reassign_order(order_number, next_id)
    except Exception:
        logger.exception("_try_reassign: ошибка reassign_order")
        return

    # Обновим сообщение у клиента
    if order["message_id"]:
        try:
            order_fresh = db.get_order(order_number)
            new_text = (
                f"🥘 Ваш заказ: {order_number}\n"
                f"Способ оплаты: {order_fresh['payment_method']}\n"
                f"Сумма: {fmt_money(order_fresh['total_price'])} ₽\n\n"
                f"Передаём заказ другому Доставщику…"
            )
            kb = B.Keyboard(inline=True)
            kb.row(B.callback_button(
                "❌ Отменить заказ",
                {"command": "cancel_order", "o": order_number},
                color=B.COLOR_NEGATIVE,
            ))
            edit_message(user_id, order["message_id"], new_text, keyboard=kb.dump())
        except Exception:
            logger.exception("_try_reassign: ошибка обновления клиенту")

    _send_order_to_courier(order_number, next_id)


# ─── Отмена заказа клиентом ─────────────────────────────────────────

@on_callback("cancel_order")
def cb_cancel_order(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("cb_cancel_order: ошибка get_order")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not order:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ не найден"})
        return

    if order["status"] != "waiting":
        status = order["status"]
        if status == "Принято":
            msg = "❌ Заказ уже принят Доставщиком и не может быть отменён"
        elif status == "Доставлено":
            msg = "✅ Заказ уже доставлен"
        else:
            msg = f"❌ Статус: {status}"
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": msg})
        return

    try:
        db.update_order_status(order_number, "Отменён")
        db.log_user_action(user_id, f"cancelled_order:{order_number}")
    except Exception:
        logger.exception("cb_cancel_order: ошибка update_order_status")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("🛒 Повторить заказ",
                             {"command": "repeat_order", "o": order_number},
                             color=B.COLOR_PRIMARY))
    kb.row(B.callback_button("🗑 Очистить корзину",
                             {"command": "clear_cart_after_cancel"},
                             color=B.COLOR_NEGATIVE))

    text = f"❌ Заказ {order_number} отменён."
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())

    # Уведомление курьеру
    courier_id     = order["courier_id"]
    courier_msg_id = order["courier_msg_id"]
    if courier_id and courier_msg_id:
        edit_message(
            courier_id, courier_msg_id,
            f"❌ Заказ {order_number} отменён пользователем.\n"
            f"Заказ больше не актуален.",
        )

    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar",
                       "text": "Заказ отменён, корзина сохранена"})


@on_callback("clear_cart_after_cancel")
def cb_clear_cart_after_cancel(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        db.clear_cart(user_id)
    except Exception:
        logger.exception("cb_clear_cart_after_cancel: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    text = ("🗑 Корзина очищена.\n\n"
            "Чтобы начать новый заказ, нажмите «📋 Смотреть меню».")
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Корзина очищена"})


# ─── Повторить отменённый заказ ─────────────────────────────────────

@on_callback("repeat_order")
def cb_repeat_order(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    old_order_number = payload.get("o")
    if not old_order_number:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        db.clear_rejected_couriers(old_order_number)
        order = db.get_order(old_order_number)
        cart_items = db.get_cart(user_id)
        phone, address = db.get_user_contact_info(user_id)
        courier_id = db.get_user_preferred_courier(user_id)
    except Exception:
        logger.exception("cb_repeat_order: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if not order:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ не найден"})
        return
    if not cart_items:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Корзина пуста"})
        return
    if not phone or not address:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Сначала заполните профиль"})
        return
    if not courier_id:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Сначала выберите Доставщика"})
        return

    new_order_number = generate_order_number()
    order_state[user_id] = {
        "step":           "awaiting_comment",
        "payment_method": order["payment_method"],
        "order_number":   new_order_number,
        "courier_id":     courier_id,
    }

    if cmid is not None:
        delete_message(peer_id, cmid)

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("Без комментария ▶",
                             {"command": "skip_comment"},
                             color=B.COLOR_SECONDARY))
    safe_send(peer_id,
              "📝 Комментарий к заказу\n\n"
              "Напишите комментарий или нажмите кнопку ниже.",
              keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Оформляем повторный заказ"})


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 5: КУРЬЕРЫ
#
#   Содержит:
#   - "🚴 Выбрать Доставщика" — клиентский выбор курьера с пагинацией
#     (по 5 на страницу — inline-лимит 6 рядов, оставляем 1 на навигацию).
#   - Курьерские callback'и (отправляются в Этапе 4):
#     * order_accept    — принимает заказ
#     * order_reject    — отказывается, заказ → следующему курьеру
#     * order_complete  — отмечает заказ доставленным, запрашивает оплату
#                          у курьера и рейтинг у клиента
#   - Запрос рейтинга клиенту (1-5 ⭐) и сохранение оценки
#   - "✅ Оплачено" / "❌ Не оплачено" сразу после доставки
#   - "📋 Неоплаченные заказы" — список с кнопкой mark_paid
#   - "📞 Мой номер для переводов" — info для курьера
#
#   Что отличается от Telegram:
#   - Inline-сообщения курьеру: после принятия Telegram-версия отправляла
#     НОВОЕ сообщение с кнопкой "Завершить" и сохраняла его msg_id в БД.
#     В VK делаем то же самое — redirect-cmid сохраняется через
#     db.set_courier_message_id. Это нужно для уведомлений админ-отмены
#     и реассайна.
#   - 5 кнопок-звёзд помещаются в один inline-ряд (лимит ряд = 5 кнопок).
# ════════════════════════════════════════════════════════════════════

COURIERS_PER_PAGE_VK = 5   # 5 курьеров + 1 ряд навигации = 6 рядов


def fmt_rating(avg: float, count: int) -> str:
    """Форматирование рейтинга '⭐⭐⭐⭐ 4.2 (15)'."""
    if not count:
        return "—"
    stars = "⭐" * round(avg)
    return f"{stars} {avg:.1f} ({count})"


# ─── "🚴 Выбрать Доставщика" — клиентский выбор ─────────────────────

def build_choose_courier_keyboard(couriers: list, page: int, total_pages: int) -> str:
    """Inline-клавиатура списка курьеров с пагинацией."""
    kb = B.Keyboard(inline=True)

    start = page * COURIERS_PER_PAGE_VK
    page_couriers = couriers[start:start + COURIERS_PER_PAGE_VK]

    for c in page_couriers:
        rating = fmt_rating(c["avg_rating"] or 0, c["ratings_count"] or 0)
        label  = f"{c['name']} · {rating}"
        if len(label) > B.MAX_LABEL_LEN:
            # Имя длинное — пытаемся сохранить рейтинг в конце
            name_room = B.MAX_LABEL_LEN - len(rating) - 4  # " · " + "…"
            if name_room > 5:
                label = f"{c['name'][:name_room]}… · {rating}"
            else:
                label = label[:B.MAX_LABEL_LEN]
        kb.row(B.callback_button(
            label,
            {"command": "pick_courier", "c": c["telegram_chat_id"]},
            color=B.COLOR_PRIMARY,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button(
                "◀", {"command": "choose_courier_page", "p": page - 1}))
        nav.append(B.callback_button(
            f"{page + 1}/{total_pages}",
            {"command": "noop"},
            color=B.COLOR_SECONDARY,
        ))
        if page < total_pages - 1:
            nav.append(B.callback_button(
                "▶", {"command": "choose_courier_page", "p": page + 1}))
        kb.row(*nav)

    return kb.dump()


@on_text(B.BTN_CHOOSE_COURIER)
def choose_courier(event):
    peer_id = event["peer_id"]
    try:
        couriers = db.get_couriers_by_rating()
    except Exception:
        logger.exception("choose_courier: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось загрузить список Доставщиков.")
        return
    if not couriers:
        safe_send(peer_id, "⚠️ Доставщики пока не добавлены.")
        return

    total_pages = max(1, (len(couriers) + COURIERS_PER_PAGE_VK - 1) // COURIERS_PER_PAGE_VK)
    safe_send(peer_id,
              "🚴 Выберите Доставщика (сортировка по рейтингу):",
              keyboard=build_choose_courier_keyboard(couriers, 0, total_pages))


@on_callback("choose_courier_page")
def cb_choose_courier_page(event, payload):
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        page = int(payload.get("p", 0))
        couriers = db.get_couriers_by_rating()
    except Exception:
        logger.exception("cb_choose_courier_page: ошибка")
        send_event_answer(event["event_id"], event["from_id"], peer_id)
        return
    if not couriers:
        send_event_answer(event["event_id"], event["from_id"], peer_id,
                          {"type": "show_snackbar", "text": "Нет Доставщиков"})
        return
    total_pages = max(1, (len(couriers) + COURIERS_PER_PAGE_VK - 1) // COURIERS_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    text = "🚴 Выберите Доставщика (сортировка по рейтингу):"
    kb   = build_choose_courier_keyboard(couriers, page, total_pages)
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], event["from_id"], peer_id)


@on_callback("pick_courier")
def cb_pick_courier(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        courier_id = int(payload["c"])
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    try:
        db.set_user_preferred_courier(user_id, courier_id)
        db.log_user_action(user_id, f"picked_courier:{courier_id}")
    except Exception:
        logger.exception("cb_pick_courier: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не удалось"})
        return

    text = "✅ Доставщик выбран. Ваши заказы пойдут к нему."
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Выбрано"})


# ─── Приём / отклонение / завершение заказа курьером ────────────────

@on_callback("order_accept")
def cb_order_accept(event, payload):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], courier_id, peer_id)
        return

    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("cb_order_accept: ошибка БД")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    if not order:
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ не найден"})
        return

    if order["status"] == "Отменён":
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Заказ уже отменён клиентом"})
        # Снимаем кнопки у этого курьера
        if cmid is not None:
            edit_message(peer_id, cmid,
                         f"❌ Заказ {order_number} отменён клиентом.")
        return

    if order["courier_id"] != courier_id:
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Заказ уже передан другому Доставщику"})
        if cmid is not None:
            edit_message(peer_id, cmid,
                         f"⌛ Заказ {order_number} передан другому Доставщику.")
        return

    user_id = order["user_id"]

    try:
        client_msg_id = db.update_order_status(order_number, "Принято")
        db.log_user_action(courier_id, f"order_accept:{order_number}")
    except Exception:
        logger.exception("cb_order_accept: ошибка update_order_status")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return

    # Сообщение клиенту
    client_text = (
        f"🥘 Ваш заказ: {order_number}\n"
        f"Статус: ✅ Принят Доставщиком\n\n"
        f"Доставщик уже в пути! Ожидайте доставку."
    )
    if client_msg_id:
        if not edit_message(user_id, client_msg_id, client_text):
            safe_send(user_id, client_text)
    else:
        safe_send(user_id, client_text)

    # Сообщение курьеру: оставляем ВСЕ детали заказа (адрес, телефон,
    # состав, сумма) — просто заменяем кнопки «Принять/Отклонить» на
    # «✅ Завершить». В Telegram-версии тут отправлялось отдельное
    # короткое сообщение «Завершить», но в VK это неудобно — курьер
    # теряет детали заказа. Поэтому редактируем то же сообщение,
    # добавляя статус-маркер в начало и оставляя остальное.
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("✅ Завершить",
                             {"command": "order_complete", "o": order_number},
                             color=B.COLOR_POSITIVE))

    # Соберём заново текст заказа (детали клиента + состав + комментарий),
    # чтобы он точно остался в сообщении.
    courier_text = _build_courier_order_text(order_number,
                                             status_prefix="✅ ПРИНЯТО")

    if cmid is not None and edit_message(peer_id, cmid, courier_text,
                                         keyboard=kb.dump()):
        # Успешно отредактировали то же сообщение, ID не меняется
        new_cmid = cmid
    else:
        # Если edit не удалось (сообщение старше 24ч и т.п.) —
        # шлём новое полное сообщение с кнопкой «Завершить».
        new_cmid = safe_send(peer_id, courier_text, keyboard=kb.dump())

    if new_cmid is not None:
        try:
            db.set_courier_message_id(order_number, new_cmid)
        except Exception:
            logger.exception("cb_order_accept: set_courier_message_id")

    send_event_answer(event["event_id"], courier_id, peer_id,
                      {"type": "show_snackbar", "text": "Заказ принят"})


@on_callback("order_reject")
def cb_order_reject(event, payload):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], courier_id, peer_id)
        return

    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("cb_order_reject: ошибка БД")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    if not order:
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ не найден"})
        return

    if order["status"] == "Отменён":
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ уже отменён"})
        return

    if order["courier_id"] != courier_id:
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Заказ уже передан другому"})
        return

    try:
        db.add_rejected_courier(order_number, courier_id)
        db.log_user_action(courier_id, f"order_reject:{order_number}")
    except Exception:
        logger.exception("cb_order_reject: add_rejected_courier")

    # Снимаем кнопки у текущего курьера
    if cmid is not None:
        edit_message(peer_id, cmid,
                     f"❌ Вы отклонили заказ {order_number}.")

    # Передаём следующему по рейтингу (или отменяем, если никого нет)
    _try_reassign(order_number, fail_reason="отклонил")

    send_event_answer(event["event_id"], courier_id, peer_id,
                      {"type": "show_snackbar", "text": "Заказ отклонён"})


@on_callback("order_complete")
def cb_order_complete(event, payload):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], courier_id, peer_id)
        return

    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("cb_order_complete: ошибка БД")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    if not order:
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ не найден"})
        return

    if order["status"] in ("Отменён", "Доставлено"):
        send_event_answer(event["event_id"], courier_id, peer_id,
                          {"type": "show_snackbar",
                           "text": f"Заказ уже в статусе «{order['status']}»"})
        return

    user_id = order["user_id"]

    try:
        client_msg_id = db.update_order_status(order_number, "Доставлено")
        db.clear_cart(user_id)
        db.log_user_action(courier_id, f"order_complete:{order_number}")
    except Exception:
        logger.exception("cb_order_complete: ошибка update_order_status")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return

    # Сообщение клиенту
    client_text = (
        f"Заказ {order_number} доставлен!\n"
        f"Спасибо, что выбрали нас 🙌"
    )
    if client_msg_id:
        if not edit_message(user_id, client_msg_id, client_text):
            safe_send(user_id, client_text)
    else:
        safe_send(user_id, client_text)

    # Снимаем «Завершить» у курьера и шлём вопрос про оплату
    if cmid is not None:
        delete_message(peer_id, cmid)

    pay_kb = B.Keyboard(inline=True)
    pay_kb.row(
        B.callback_button("✅ Оплачено",
                          {"command": "order_paid", "o": order_number},
                          color=B.COLOR_POSITIVE),
        B.callback_button("❌ Не оплачено",
                          {"command": "order_unpaid", "o": order_number},
                          color=B.COLOR_NEGATIVE),
    )
    safe_send(peer_id,
              f"✅ Заказ {order_number} завершён!\n\nКлиент оплатил заказ?",
              keyboard=pay_kb.dump())

    # Запрос рейтинга клиенту
    _ask_rating(user_id, order_number, courier_id)

    send_event_answer(event["event_id"], courier_id, peer_id,
                      {"type": "show_snackbar", "text": "Доставлено"})


# ─── Рейтинг ────────────────────────────────────────────────────────

def _ask_rating(user_id: int, order_number: str, courier_id: int) -> None:
    kb = B.Keyboard(inline=True)
    # 5 звёзд в одном ряду (лимит ряд = 5 кнопок)
    kb.row(*[
        B.callback_button(
            "⭐" * stars,
            {"command": "rate", "o": order_number, "c": courier_id, "s": stars},
            color=B.COLOR_PRIMARY,
        )
        for stars in range(1, 6)
    ])
    safe_send(user_id,
              f"🙏 Оцените работу Доставщика по заказу {order_number}:",
              keyboard=kb.dump())


@on_callback("rate")
def cb_rate(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        order_number = payload["o"]
        courier_id   = int(payload["c"])
        stars        = int(payload["s"])
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not 1 <= stars <= 5:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        ok = db.save_rating(order_number, courier_id, user_id, stars)
    except Exception:
        logger.exception("cb_rate: ошибка save_rating")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка"})
        return

    if ok:
        text = f"Спасибо за оценку! Вы поставили {'⭐' * stars}."
        if cmid is None or not edit_message(peer_id, cmid, text):
            safe_send(peer_id, text)
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Оценка сохранена"})
    else:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Вы уже оценивали этот заказ"})


# ─── Оплачено / не оплачено ─────────────────────────────────────────

@on_callback("order_paid")
def cb_order_paid(event, payload):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    try:
        db.mark_order_paid(order_number, paid=True)
        db.log_user_action(courier_id, f"order_paid:{order_number}")
    except Exception:
        logger.exception("cb_order_paid: ошибка БД")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    text = f"✅ Заказ {order_number} отмечен как оплаченный."
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], courier_id, peer_id,
                      {"type": "show_snackbar", "text": "Отмечено как оплачено"})


@on_callback("order_unpaid")
def cb_order_unpaid(event, payload):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    try:
        db.mark_order_paid(order_number, paid=False)
        db.log_user_action(courier_id, f"order_unpaid:{order_number}")
    except Exception:
        logger.exception("cb_order_unpaid: ошибка БД")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    text = (
        f"❌ Заказ {order_number} отмечен как НЕОПЛАЧЕННЫЙ.\n"
        f"Посмотреть список можно через «📋 Неоплаченные заказы»."
    )
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], courier_id, peer_id,
                      {"type": "show_snackbar", "text": "Отмечено"})


# ─── "📋 Неоплаченные заказы" ───────────────────────────────────────

@on_text(B.BTN_UNPAID_ORDERS)
def show_unpaid_orders(event):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    if not is_courier(courier_id):
        safe_send(peer_id, "Эта функция доступна только Доставщикам.")
        return
    try:
        unpaid = db.get_unpaid_orders_for_courier(courier_id)
    except Exception:
        logger.exception("show_unpaid_orders: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось загрузить список.")
        return

    if not unpaid:
        safe_send(peer_id, "✅ У вас нет неоплаченных заказов!")
        return

    safe_send(peer_id, f"📋 Неоплаченные заказы ({len(unpaid)} шт):")
    for order in unpaid:
        user_id = order["user_id"]
        try:
            pii = db.get_user_pii(user_id)
            name    = pii["name"]    or "—"
            phone   = pii["phone"]   or "—"
            address = pii["address"] or "—"
        except Exception:
            name, phone, address = "—", "—", "—"

        text = (
            f"📋 Заказ {order['order_number']}\n"
            f"💰 Сумма: {fmt_money(order['total_price'])} ₽\n"
            f"💳 Способ оплаты: {order['payment_method']}\n"
            f"📅 Доставлен: {order['delivered_at'] or '—'}\n\n"
            f"👤 Клиент: {name}\n"
            f"📱 Телефон: {phone}\n"
            f"🏠 Адрес: {address}"
        )
        kb = B.Keyboard(inline=True)
        kb.row(B.callback_button(
            "✅ Отметить как оплачено",
            {"command": "mark_paid", "o": order["order_number"]},
            color=B.COLOR_POSITIVE,
        ))
        safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("mark_paid")
def cb_mark_paid(event, payload):
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    try:
        db.mark_order_paid(order_number, paid=True)
        db.log_user_action(courier_id, f"marked_paid:{order_number}")
    except Exception:
        logger.exception("cb_mark_paid: ошибка БД")
        send_event_answer(event["event_id"], courier_id, peer_id)
        return
    text = f"✅ Заказ {order_number} отмечен как оплаченный!"
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], courier_id, peer_id,
                      {"type": "show_snackbar", "text": "Отмечено как оплачено"})


# ─── "📞 Мой номер для переводов" ───────────────────────────────────

@on_text(B.BTN_MY_PHONE)
def courier_show_my_phone(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_courier(user_id):
        safe_send(peer_id, "Эта функция доступна только Доставщикам.")
        return
    try:
        phone   = db.get_courier_phone(user_id)
        courier = db.get_courier_by_chat_id(user_id)
        name    = courier["name"] if courier else "Доставщик"
    except Exception:
        logger.exception("courier_show_my_phone: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось получить номер.")
        return

    if phone:
        safe_send(peer_id,
                  f"📞 {name}, ваш номер для переводов:\n"
                  f"{phone}\n\n"
                  f"⚠️ Этот номер видят клиенты при выборе оплаты переводом.\n"
                  f"Если номер неверный, обратитесь к администратору.")
    else:
        safe_send(peer_id,
                  f"⚠️ {name}, у вас не указан номер для переводов.\n\n"
                  f"Пожалуйста, обратитесь к администратору, чтобы он "
                  f"добавил ваш номер.")


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 6: АДМИНКА — управление меню, блюдами, фото
#
#   Подразделы:
#   1. Категории — список, добавить, удалить (с каскадом блюд)
#   2. Добавить блюдо — выбор категории → название → цена
#   3. Удалить блюдо — выбор категории → блюдо (с пагинацией) → удалить
#   4. Скрыть/Вернуть блюдо — выбор категории → блюдо
#   5. Скрыть/Вернуть всё меню
#   6. Список скрытых
#   7. Добавить фото — выбор категории → блюдо → отправить фото
#   8. Удалить фото — выбор категории → блюдо → подтверждение
#
#   FSM для админа в admin_state[user_id] = {"action": "..."}
#
#   Что важно отличается от Telegram:
#   - Фото: VK даёт photo-attachment прямо в event["attachments"].
#     Формируем строку "photo<owner_id>_<id>[_<access_key>]" и кладём в БД.
#     Никакого upload не нужно.
#   - inline-клавиатуры строго ≤6 рядов. DISHES_PER_PAGE_ADMIN = 4.
# ════════════════════════════════════════════════════════════════════

DISHES_PER_PAGE_ADMIN = 4   # 4 блюда + 1 ряд навигации + 1 ряд "назад" = 6


# ─── 1. КАТЕГОРИИ ───────────────────────────────────────────────────

@on_text(B.BTN_CATEGORIES)
def admin_categories_menu(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("admin_categories_menu: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка загрузки категорий.")
        return

    if categories:
        lines = "\n".join(f"• {c['name']}" for c in categories)
        text = f"📁 Категории меню:\n\n{lines}\n\nВыберите действие:"
    else:
        text = "📁 Категорий пока нет.\n\nВыберите действие:"

    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("➕ Добавить категорию",
                          {"command": "cat_add"},
                          color=B.COLOR_POSITIVE),
    )
    if categories:
        kb.row(B.callback_button("❌ Удалить категорию",
                                 {"command": "cat_del_list"},
                                 color=B.COLOR_NEGATIVE))
    kb.row(B.callback_button("Закрыть",
                             {"command": "cat_close"},
                             color=B.COLOR_SECONDARY))
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("cat_close")
def cb_cat_close(event, payload):
    cmid = event.get("conversation_message_id")
    if cmid is not None:
        delete_message(event["peer_id"], cmid)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


@on_callback("cat_add")
def cb_cat_add(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    admin_state[user_id] = {"action": "add_category"}
    safe_send(peer_id,
              "Введите название новой категории.\n"
              "Отправьте «отмена», чтобы прервать.")
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("cat_del_list")
def cb_cat_del_list(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("cb_cat_del_list: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not categories:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет категорий"})
        return

    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0

    # 8 категорий на странице (4 ряда × 2 кнопки) + 1 ряд навигации + 1 ряд отмены = 6
    total_pages = max(1, (len(categories) + CATEGORIES_PER_PAGE_VK - 1)
                         // CATEGORIES_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * CATEGORIES_PER_PAGE_VK
    page_cats = categories[start:start + CATEGORIES_PER_PAGE_VK]

    kb = B.Keyboard(inline=True)
    row: list = []
    for c in page_cats:
        row.append(B.callback_button(
            f"❌ {c['name']}"[:B.MAX_LABEL_LEN],
            {"command": "cat_del", "c": c["id"]},
            color=B.COLOR_NEGATIVE,
        ))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "cat_del_list", "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "cat_del_list", "p": page + 1}))
        kb.row(*nav)

    kb.row(B.callback_button("Отмена",
                             {"command": "cat_close"},
                             color=B.COLOR_SECONDARY))

    text = "⚠️ Выберите категорию для удаления (все блюда в ней удалятся):"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("cat_del")
def cb_cat_del(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        name = db.get_category_name(category_id)
        db.delete_category(category_id)
        db.log_user_action(user_id, f"deleted_category:{name}")
    except Exception:
        logger.exception("cb_cat_del: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не удалось"})
        return
    text = f"✅ Категория «{name}» и все блюда в ней удалены."
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Удалено"})


# Универсальная отмена админских FSM-ов
def _admin_in_action(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") in (
                "add_category", "add_dish_name", "add_dish_price"))


@on_state(_admin_in_action)
def admin_action_router(event):
    """Маршрутизатор по action в admin_state."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = admin_state.get(user_id, {})
    action  = state.get("action")

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    if action == "add_category":
        if not text:
            safe_send(peer_id, "⚠️ Название не может быть пустым.")
            return
        try:
            db.add_category(text)
            db.log_user_action(user_id, f"added_category:{text}")
        except Exception:
            logger.exception("add_category: ошибка БД")
            admin_state.pop(user_id, None)
            safe_send(peer_id, "⚠️ Не удалось добавить (возможно, такая уже есть).")
            return
        admin_state.pop(user_id, None)
        safe_send(peer_id, f"✅ Категория «{text}» добавлена.")
        return

    if action == "add_dish_name":
        if not text:
            safe_send(peer_id, "⚠️ Пустое название. Введите ещё раз или «отмена».")
            return
        state["dish_name"] = text
        state["action"]    = "add_dish_price"
        safe_send(peer_id, "Введите цену (число, можно с копейками):")
        return

    if action == "add_dish_price":
        try:
            price = float(text.replace(",", ".").strip())
        except ValueError:
            safe_send(peer_id,
                      "⚠️ Не число. Введите цену цифрами (например 250 или 199.50) "
                      "или «отмена».")
            return
        if price <= 0:
            safe_send(peer_id, "⚠️ Цена должна быть больше 0.")
            return
        cat_id    = state["category_id"]
        dish_name = state["dish_name"]
        try:
            cat_name = db.get_category_name(cat_id)
            db.add_menu_item(dish_name, price, cat_id)
            db.log_user_action(user_id, f"added_dish:{dish_name}")
        except Exception:
            logger.exception("add_dish: ошибка БД")
            admin_state.pop(user_id, None)
            safe_send(peer_id, "⚠️ Не удалось сохранить блюдо.")
            return
        admin_state.pop(user_id, None)
        safe_send(peer_id,
                  f"✅ «{dish_name}» добавлено в «{cat_name}» за {fmt_money(price)} ₽.")
        return


# ─── 2. ДОБАВИТЬ БЛЮДО ──────────────────────────────────────────────

def _build_categories_keyboard_for_admin(cb_command: str,
                                         extra_payload: Optional[dict] = None,
                                         label_prefix: str = "",
                                         page_command: Optional[str] = None,
                                         page: int = 0) -> Optional[str]:
    """
    Построить inline-клавиатуру категорий для админских действий с пагинацией.

    Args:
        cb_command:    команда callback при клике на категорию.
        extra_payload: дополнительные поля в payload (например {"p": 0}).
        label_prefix:  префикс к названию категории (например "➕ ").
        page_command:  команда callback для смены страницы. Если не задана,
                       используется cb_command + "_p".
        page:          текущая страница.
    """
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("get_categories: ошибка БД")
        return None
    if not categories:
        return None

    if page_command is None:
        page_command = cb_command + "_page"

    total_pages = max(1, (len(categories) + CATEGORIES_PER_PAGE_VK - 1)
                         // CATEGORIES_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * CATEGORIES_PER_PAGE_VK
    page_cats = categories[start:start + CATEGORIES_PER_PAGE_VK]

    kb = B.Keyboard(inline=True)
    row: list = []
    for cat in page_cats:
        payload = {"command": cb_command, "c": cat["id"]}
        if extra_payload:
            payload.update(extra_payload)
        label = f"{label_prefix}{cat['name']}"[:B.MAX_LABEL_LEN]
        row.append(B.callback_button(label, payload, color=B.COLOR_PRIMARY))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                                         {"command": page_command, "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                                         {"command": page_command, "p": page + 1}))
        kb.row(*nav)

    return kb.dump()


@on_text(B.BTN_ADD_DISH)
def admin_add_dish(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("admin_add_dish: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка загрузки категорий.")
        return
    if not categories:
        safe_send(peer_id,
                  "⚠️ Сначала добавьте хотя бы одну категорию через «📁 Категории».")
        return
    kb = _build_categories_keyboard_for_admin("add_dish_cat", label_prefix="➕ ")
    safe_send(peer_id, "Выберите категорию для нового блюда:", keyboard=kb)


@on_callback("add_dish_cat")
def cb_add_dish_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        cat_name    = db.get_category_name(category_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    admin_state[user_id] = {
        "action":      "add_dish_name",
        "category_id": category_id,
    }
    safe_send(peer_id,
              f"Категория: «{cat_name}»\n\n"
              "Введите название нового блюда.\n"
              "Отправьте «отмена», чтобы прервать.")
    send_event_answer(event["event_id"], user_id, peer_id)


# После cb_add_dish_cat (строка ~2030) добавьте:
@on_callback("add_dish_cat_page")
def cb_add_dish_cat_page(event, payload):
    """Пагинация категорий при добавлении блюда."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0

    kb = _build_categories_keyboard_for_admin("add_dish_cat",
                                              extra_payload={"p": 0},
                                              label_prefix="➕ ",
                                              page_command="add_dish_cat_page",
                                              page=page)
    if kb is None:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет категорий"})
        return

    text = "Выберите категорию для нового блюда:"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id)
# ─── 3. УДАЛИТЬ БЛЮДО ───────────────────────────────────────────────

@on_text(B.BTN_DELETE_DISH)
def admin_del_dish(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        categories = db.get_categories()
    except Exception:
        logger.exception("admin_del_dish: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return
    if not categories:
        safe_send(peer_id, "Нет категорий.")
        return
    kb = _build_categories_keyboard_for_admin("del_dish_cat", {"p": 0},
                                              label_prefix="❌ ")
    safe_send(peer_id, "❌ Выберите категорию для удаления блюд:", keyboard=kb)


def _send_dishes_for_delete(peer_id: int, category_id: int, page: int,
                            *, conversation_message_id: Optional[int] = None) -> None:
    """Показать страницу блюд категории с кнопками удаления."""
    try:
        cat_name = db.get_category_name(category_id)
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, price, frozen FROM menu "
                      "WHERE category_id = ? ORDER BY name", (category_id,))
            dishes = c.fetchall()
    except Exception:
        logger.exception("_send_dishes_for_delete: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if not dishes:
        safe_send(peer_id, f"В категории «{cat_name}» нет блюд.")
        return

    total_pages = max(1, (len(dishes) + DISHES_PER_PAGE_ADMIN - 1) // DISHES_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * DISHES_PER_PAGE_ADMIN
    page_dishes = dishes[start:start + DISHES_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for d in page_dishes:
        prefix = "🔒 " if d["frozen"] else ""
        label = f"❌ {prefix}{d['name']} — {fmt_money(d['price'])} ₽"
        if len(label) > B.MAX_LABEL_LEN:
            # Сокращаем имя, сохраняя цену
            suffix = f" — {fmt_money(d['price'])} ₽"
            avail = B.MAX_LABEL_LEN - len(suffix) - len("❌ ") - len(prefix) - 1
            if avail > 5:
                name_short = d["name"][:avail] + "…"
            else:
                name_short = d["name"][:5]
            label = f"❌ {prefix}{name_short}{suffix}"
        kb.row(B.callback_button(
            label,
            {"command": "del_dish_do", "d": d["id"], "c": category_id, "p": page},
            color=B.COLOR_NEGATIVE,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "del_dish_cat", "c": category_id, "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "del_dish_cat", "c": category_id, "p": page + 1}))
        kb.row(*nav)

    text = f"❌ {cat_name} — выберите блюдо для удаления:"
    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb.dump()):
            return
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("del_dish_cat")
def cb_del_dish_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    _send_dishes_for_delete(peer_id, category_id, page,
                            conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


# После cb_del_dish_cat (строка ~2140) добавьте:
@on_callback("del_dish_cat_page")
def cb_del_dish_cat_page(event, payload):
    """Пагинация категорий при удалении блюда."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0

    kb = _build_categories_keyboard_for_admin("del_dish_cat",
                                              extra_payload={"p": 0},
                                              label_prefix="❌ ",
                                              page_command="del_dish_cat_page",
                                              page=page)
    if kb is None:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет категорий"})
        return

    text = "❌ Выберите категорию для удаления блюд:"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id)
@on_callback("del_dish_do")
def cb_del_dish_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        dish_id     = int(payload["d"])
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
        item = db.get_menu_item_by_id(dish_id)
    except Exception:
        logger.exception("cb_del_dish_do: ошибка")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if not item:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Блюдо не найдено"})
        return

    try:
        db.delete_menu_item(item["name"], item["category_id"])
        db.log_user_action(user_id, f"deleted_dish:{item['name']}")
    except Exception:
        logger.exception("cb_del_dish_do: delete_menu_item")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка удаления"})
        return

    # Обновим экран на ту же страницу
    _send_dishes_for_delete(peer_id, category_id, page,
                            conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": f"«{item['name']}» удалено"})


# ─── 4. СКРЫТЬ / ВЕРНУТЬ БЛЮДО ──────────────────────────────────────

@on_text(B.BTN_FREEZE_DISH)
def admin_freeze_list(event):
    if not is_admin(event["from_id"]):
        return
    kb = _build_categories_keyboard_for_admin("frz_cat", {"p": 0, "m": "f"},
                                              label_prefix="🥶 ")
    if kb is None:
        safe_send(event["peer_id"], "Нет категорий.")
        return
    safe_send(event["peer_id"],
              "🥶 Выберите категорию для скрытия блюд:", keyboard=kb)


@on_text(B.BTN_UNFREEZE_DISH)
def admin_unfreeze_list(event):
    if not is_admin(event["from_id"]):
        return
    kb = _build_categories_keyboard_for_admin("frz_cat", {"p": 0, "m": "u"},
                                              label_prefix="☀️ ")
    if kb is None:
        safe_send(event["peer_id"], "Нет категорий.")
        return
    safe_send(event["peer_id"],
              "☀️ Выберите категорию для возврата блюд:", keyboard=kb)


def _send_dishes_for_freeze(peer_id: int, category_id: int, page: int, mode: str,
                            *, conversation_message_id: Optional[int] = None) -> None:
    """mode: 'f' (freeze, показываем доступные) или 'u' (unfreeze, показываем скрытые)."""
    try:
        cat_name = db.get_category_name(category_id)
        if mode == "f":
            items = db.get_menu_items_available(category_id)
        else:
            items = db.get_menu_items_frozen(category_id)
    except Exception:
        logger.exception("_send_dishes_for_freeze: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if not items:
        msg = ("✅ Все блюда уже скрыты или категория пустая."
               if mode == "f" else "Нет скрытых блюд в этой категории.")
        if conversation_message_id is not None:
            edit_message(peer_id, conversation_message_id, msg)
        else:
            safe_send(peer_id, msg)
        return

    total_pages = max(1, (len(items) + DISHES_PER_PAGE_ADMIN - 1) // DISHES_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * DISHES_PER_PAGE_ADMIN
    page_items = items[start:start + DISHES_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for it in page_items:
        label = f"{it['name']} — {fmt_money(it['price'])} ₽"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": "frz_do", "d": it["id"], "c": category_id,
             "p": page, "m": mode},
            color=(B.COLOR_PRIMARY if mode == "f" else B.COLOR_POSITIVE),
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "frz_cat", "c": category_id, "p": page - 1, "m": mode}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "frz_cat", "c": category_id, "p": page + 1, "m": mode}))
        kb.row(*nav)

    title = ("🥶" if mode == "f" else "☀️") + f" {cat_name} — выберите блюдо:"
    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, title, keyboard=kb.dump()):
            return
    safe_send(peer_id, title, keyboard=kb.dump())


@on_callback("frz_cat")
def cb_frz_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
        mode        = payload.get("m", "f")
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    _send_dishes_for_freeze(peer_id, category_id, page, mode,
                            conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


# После cb_frz_cat (строка ~2220) добавьте:
@on_callback("frz_cat_page")
def cb_frz_cat_page(event, payload):
    """Пагинация категорий при скрытии/возврате блюда."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
        mode = payload.get("m", "f")
    except (ValueError, TypeError):
        page = 0
        mode = "f"

    label_prefix = "🥶 " if mode == "f" else "☀️ "
    kb = _build_categories_keyboard_for_admin("frz_cat",
                                              extra_payload={"p": 0, "m": mode},
                                              label_prefix=label_prefix,
                                              page_command="frz_cat_page",
                                              page=page)
    if kb is None:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет категорий"})
        return

    text = "🥶 Выберите категорию для скрытия блюд:" if mode == "f" else "☀️ Выберите категорию для возврата блюд:"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("frz_do")
def cb_frz_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        dish_id     = int(payload["d"])
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
        mode        = payload.get("m", "f")
        freeze      = (mode == "f")
        name = db.set_dish_frozen_by_id(dish_id, freeze)
        if name:
            db.log_user_action(user_id,
                               f"{'froze' if freeze else 'unfroze'}_dish:{name}")
    except Exception:
        logger.exception("cb_frz_do: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if not name:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Блюдо не найдено"})
        return

    # Перерисовываем список — он мог измениться
    _send_dishes_for_freeze(peer_id, category_id, 0, mode,
                            conversation_message_id=cmid)
    word = "скрыто" if freeze else "снова доступно"
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": f"«{name}»: {word}"})


# ─── 5. СКРЫТЬ / ВЕРНУТЬ ВСЁ МЕНЮ ───────────────────────────────────

@on_text(B.BTN_FREEZE_ALL)
def admin_freeze_all(event):
    user_id = event["from_id"]
    if not is_admin(user_id):
        return
    try:
        n = db.set_all_dishes_frozen(True)
        db.log_user_action(user_id, "froze_all")
    except Exception:
        logger.exception("admin_freeze_all: ошибка БД")
        safe_send(event["peer_id"], "⚠️ Ошибка БД.")
        return
    safe_send(event["peer_id"], f"🥶 Скрыто блюд: {n}.")


@on_text(B.BTN_UNFREEZE_ALL)
def admin_unfreeze_all(event):
    user_id = event["from_id"]
    if not is_admin(user_id):
        return
    try:
        n = db.set_all_dishes_frozen(False)
        db.log_user_action(user_id, "unfroze_all")
    except Exception:
        logger.exception("admin_unfreeze_all: ошибка БД")
        safe_send(event["peer_id"], "⚠️ Ошибка БД.")
        return
    safe_send(event["peer_id"], f"☀️ Возвращено блюд: {n}.")


# ─── 6. СПИСОК СКРЫТЫХ ──────────────────────────────────────────────

@on_text(B.BTN_LIST_FROZEN)
def admin_list_frozen(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        rows = db.get_menu_items_frozen()
    except Exception:
        logger.exception("admin_list_frozen: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return
    if not rows:
        safe_send(peer_id, "Нет скрытых блюд.")
        return
    text = "📜 Скрытые блюда:\n" + "\n".join(
        f"• {r['name']} — {fmt_money(r['price'])} ₽" for r in rows
    )
    # VK лимит 4096 символов на сообщение — отрежем, если очень много
    if len(text) > 4000:
        text = text[:3990] + "\n…(список обрезан)"
    safe_send(peer_id, text)


# ─── 7. ДОБАВИТЬ ФОТО ───────────────────────────────────────────────

def _extract_vk_photo_from_attachments(attachments: list) -> Optional[str]:
    """
    Из списка attachments выбрать первое фото и собрать строку
    "photo<owner_id>_<id>[_<access_key>]" для использования в messages.send.
    """
    if not attachments:
        return None
    for att in attachments:
        if not isinstance(att, dict) or att.get("type") != "photo":
            continue
        photo = att.get("photo") or {}
        owner = photo.get("owner_id")
        pid   = photo.get("id")
        if owner is None or pid is None:
            continue
        key = photo.get("access_key")
        if key:
            return f"photo{owner}_{pid}_{key}"
        return f"photo{owner}_{pid}"
    return None


@on_text(B.BTN_ADD_PHOTO)
def admin_add_photo_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    _admin_add_photo_show(peer_id, page=0)


@on_callback("addph_page")
def cb_addph_page(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _admin_add_photo_show(peer_id, page=page,
                          conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


def _admin_add_photo_show(peer_id: int, page: int = 0,
                          *, conversation_message_id: Optional[int] = None) -> None:
    # Категории, в которых есть нескрытые блюда
    try:
        categories = db.get_categories()
        with db.conn_ctx() as conn:
            c = conn.cursor()
            counts = {}
            for cat in categories:
                c.execute("SELECT COUNT(*) AS n FROM menu "
                          "WHERE category_id = ? AND frozen = 0", (cat["id"],))
                counts[cat["id"]] = c.fetchone()["n"]
    except Exception:
        logger.exception("_admin_add_photo_show: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    cats_with_dishes = [c for c in categories if counts.get(c["id"], 0) > 0]
    if not cats_with_dishes:
        safe_send(peer_id, "⚠️ Нет доступных блюд для добавления фото.")
        return

    total_pages = max(1, (len(cats_with_dishes) + CATEGORIES_PER_PAGE_VK - 1)
                         // CATEGORIES_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * CATEGORIES_PER_PAGE_VK
    page_cats = cats_with_dishes[start:start + CATEGORIES_PER_PAGE_VK]

    kb = B.Keyboard(inline=True)
    row: list = []
    for cat in page_cats:
        label = f"📸 {cat['name']} ({counts[cat['id']]})"
        row.append(B.callback_button(
            label[:B.MAX_LABEL_LEN],
            {"command": "ph_cat", "c": cat["id"], "p": 0},
            color=B.COLOR_PRIMARY,
        ))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "addph_page", "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "addph_page", "p": page + 1}))
        kb.row(*nav)

    text = "📸 Выберите категорию с блюдом для добавления фото:"
    if conversation_message_id is not None and edit_message(
            peer_id, conversation_message_id, text, keyboard=kb.dump()):
        return
    safe_send(peer_id, text, keyboard=kb.dump())


def _send_dishes_for_photo(peer_id: int, category_id: int, page: int,
                           *, conversation_message_id: Optional[int] = None) -> None:
    """Показать блюда категории с маркером — есть/нет фото."""
    try:
        cat_name = db.get_category_name(category_id)
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, price, photo FROM menu "
                      "WHERE category_id = ? AND frozen = 0 ORDER BY name",
                      (category_id,))
            dishes = c.fetchall()
    except Exception:
        logger.exception("_send_dishes_for_photo: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if not dishes:
        safe_send(peer_id, f"В категории «{cat_name}» нет доступных блюд.")
        return

    total_pages = max(1, (len(dishes) + DISHES_PER_PAGE_ADMIN - 1) // DISHES_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * DISHES_PER_PAGE_ADMIN
    page_dishes = dishes[start:start + DISHES_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for d in page_dishes:
        emoji = "📸" if is_vk_photo_attachment(d["photo"]) else "📷"
        label = f"{emoji} {d['name']} — {fmt_money(d['price'])} ₽"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": "ph_dish", "d": d["id"]},
            color=B.COLOR_PRIMARY,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "ph_cat", "c": category_id, "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "ph_cat", "c": category_id, "p": page + 1}))
        kb.row(*nav)

    text = f"📸 {cat_name} — выберите блюдо (📸 = фото уже есть):"
    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb.dump()):
            return
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("ph_cat")
def cb_ph_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    _send_dishes_for_photo(peer_id, category_id, page,
                           conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("ph_dish")
def cb_ph_dish(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        menu_id = int(payload["d"])
        dish = db.get_menu_item_by_id(menu_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not dish:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Блюдо не найдено"})
        return

    admin_state[user_id] = {
        "action":    "add_photo",
        "menu_id":   menu_id,
        "dish_name": dish["name"],
    }
    text = (
        f"📸 Добавление фото для: {dish['name']}\n\n"
        f"Отправьте фотографию следующим сообщением.\n"
        f"Можно прикрепить через скрепку.\n\n"
        f"Чтобы отменить — отправьте «отмена»."
    )
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_admin_awaiting_photo(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "add_photo")


@on_state(_is_admin_awaiting_photo)
def admin_receive_photo(event):
    """
    Принимаем фото от админа. В VK фото приходит в attachments сообщения.
    Если фото нет, но есть текст «отмена» — отменяем.
    """
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip().lower()
    state   = admin_state.get(user_id) or {}

    if text in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    photo_attach = _extract_vk_photo_from_attachments(event.get("attachments") or [])
    if not photo_attach:
        safe_send(peer_id,
                  "⚠️ В сообщении нет фотографии. Прикрепите фото через "
                  "скрепку 📎 или отправьте «отмена».")
        return

    menu_id   = state.get("menu_id")
    dish_name = state.get("dish_name", "блюдо")
    if not menu_id:
        admin_state.pop(user_id, None)
        safe_send(peer_id, "⚠️ Состояние потеряно, начните заново.")
        return

    try:
        db.set_dish_photo(menu_id, photo_attach)
        db.log_user_action(user_id, f"added_photo:{dish_name}")
    except Exception:
        logger.exception("admin_receive_photo: ошибка БД")
        admin_state.pop(user_id, None)
        safe_send(peer_id, "⚠️ Не удалось сохранить фото.")
        return

    admin_state.pop(user_id, None)
    safe_send(peer_id,
              f"✅ Фото для «{dish_name}» сохранено.\n\n"
              f"Проверить: «📋 Смотреть меню» → найти блюдо со значком 📸.")


# ─── 8. УДАЛИТЬ ФОТО ───────────────────────────────────────────────

@on_text(B.BTN_DELETE_PHOTO)
def admin_delete_photo_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    _admin_delete_photo_show(peer_id, page=0)


@on_callback("delph_page")
def cb_delph_page(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _admin_delete_photo_show(peer_id, page=page,
                             conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


def _admin_delete_photo_show(peer_id: int, page: int = 0,
                             *, conversation_message_id: Optional[int] = None) -> None:
    try:
        categories = db.get_categories()
        with db.conn_ctx() as conn:
            c = conn.cursor()
            counts = {}
            for cat in categories:
                c.execute("SELECT COUNT(*) AS n FROM menu "
                          "WHERE category_id = ? AND photo IS NOT NULL "
                          "AND photo != ''", (cat["id"],))
                counts[cat["id"]] = c.fetchone()["n"]
    except Exception:
        logger.exception("_admin_delete_photo_show: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    cats_with_photos = [c for c in categories if counts.get(c["id"], 0) > 0]
    if not cats_with_photos:
        safe_send(peer_id, "⚠️ Нет блюд с фото.")
        return

    total_pages = max(1, (len(cats_with_photos) + CATEGORIES_PER_PAGE_VK - 1)
                         // CATEGORIES_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * CATEGORIES_PER_PAGE_VK
    page_cats = cats_with_photos[start:start + CATEGORIES_PER_PAGE_VK]

    kb = B.Keyboard(inline=True)
    row: list = []
    for cat in page_cats:
        label = f"🗑 {cat['name']} ({counts[cat['id']]})"
        row.append(B.callback_button(
            label[:B.MAX_LABEL_LEN],
            {"command": "delph_cat", "c": cat["id"], "p": 0},
            color=B.COLOR_NEGATIVE,
        ))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "delph_page", "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "delph_page", "p": page + 1}))
        kb.row(*nav)

    text = "🗑 Выберите категорию для удаления фото:"
    if conversation_message_id is not None and edit_message(
            peer_id, conversation_message_id, text, keyboard=kb.dump()):
        return
    safe_send(peer_id, text, keyboard=kb.dump())


def _send_dishes_for_delete_photo(peer_id: int, category_id: int, page: int,
                                  *, conversation_message_id: Optional[int] = None) -> None:
    try:
        cat_name = db.get_category_name(category_id)
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, price FROM menu "
                      "WHERE category_id = ? AND photo IS NOT NULL "
                      "AND photo != '' ORDER BY name", (category_id,))
            dishes = c.fetchall()
    except Exception:
        logger.exception("_send_dishes_for_delete_photo: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if not dishes:
        msg = f"В категории «{cat_name}» больше нет блюд с фото."
        if conversation_message_id is not None:
            edit_message(peer_id, conversation_message_id, msg)
        else:
            safe_send(peer_id, msg)
        return

    total_pages = max(1, (len(dishes) + DISHES_PER_PAGE_ADMIN - 1) // DISHES_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * DISHES_PER_PAGE_ADMIN
    page_dishes = dishes[start:start + DISHES_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for d in page_dishes:
        label = f"🗑 {d['name']} — {fmt_money(d['price'])} ₽"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": "delph_do", "d": d["id"], "c": category_id, "p": page},
            color=B.COLOR_NEGATIVE,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "delph_cat", "c": category_id, "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "delph_cat", "c": category_id, "p": page + 1}))
        kb.row(*nav)

    text = f"🗑 {cat_name} — выберите блюдо для удаления фото:"
    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb.dump()):
            return
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("delph_cat")
def cb_delph_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    _send_dishes_for_delete_photo(peer_id, category_id, page,
                                  conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("delph_do")
def cb_delph_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        dish_id     = int(payload["d"])
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
        dish = db.get_menu_item_by_id(dish_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not dish:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Блюдо не найдено"})
        return

    try:
        db.set_dish_photo(dish_id, None)
        db.log_user_action(user_id, f"deleted_photo:{dish['name']}")
    except Exception:
        logger.exception("cb_delph_do: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка"})
        return

    _send_dishes_for_delete_photo(peer_id, category_id, page,
                                  conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar",
                       "text": f"Фото у «{dish['name']}» удалено"})


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 7: АДМИН-КУРЬЕРЫ
#
#   - "➕ Нанять Доставщика": редизайн под VK.
#     В Telegram админ пересылал контакт из адресной книги — в VK так нельзя.
#     Поддерживаем три способа:
#       a) ссылка на профиль: https://vk.com/id12345 или vk.com/<screen_name>
#       b) просто screen_name (без префикса) или числовой ID
#       c) пересылка любого сообщения от курьера (forward / reply)
#     После получения VK-ID — резолв имени через users.get, опционально
#     ввод телефона, подтверждение.
#   - "❌ Уволить Доставщика": список с пагинацией → подтверждение.
#   - "📱 Изменить номер Доставщика для переводов".
#   - "📋 Список Доставщиков".
#   - "🆔 Найти VK-ID": по номеру заказа.
#   - "📩 Написать Доставщикам": рассылка по всем курьерам.
#
#   FSM в admin_state, ключи действий:
#     "hire_input"          — ждём ссылку/ID/forward
#     "hire_phone"          — ждём телефон (или пропуск)
#     "edit_courier_phone"  — ждём новый телефон выбранного курьера
#     "find_chat_id"        — ждём номер заказа
#     "msg_couriers"        — ждём текст рассылки
# ════════════════════════════════════════════════════════════════════

import re as _re_courier  # отдельный alias, чтобы не конфликтовать с re выше


# ─── Утилиты резолва VK-ID ──────────────────────────────────────────

_VK_PROFILE_RE = _re_courier.compile(
    r"^(?:https?://)?(?:m\.)?vk\.com/([A-Za-z0-9_.]+)/?$",
    _re_courier.IGNORECASE,
)


def _resolve_vk_user(query: str) -> Optional[dict]:
    """
    Из строки (ссылка/ID/screen_name) получить
    {"id": int, "name": "...", "screen_name": "..."} или None.

    query может быть:
      "https://vk.com/id12345"
      "vk.com/durov"
      "durov"
      "id12345"
      "12345"
    """
    if not query:
        return None
    q = query.strip()

    # Если это ссылка — извлекаем хвост
    m = _VK_PROFILE_RE.match(q)
    if m:
        q = m.group(1)

    # Чистый числовой ID
    if q.isdigit():
        try:
            res = vk.users.get(user_ids=q)
        except Exception:
            logger.exception("_resolve_vk_user: vk.users.get(id) ошибка")
            return None
        if not res:
            return None
        u = res[0]
        return {
            "id":          int(u["id"]),
            "name":        f"{u.get('first_name','').strip()} "
                           f"{u.get('last_name','').strip()}".strip()
                           or f"VK-{u['id']}",
            "screen_name": u.get("screen_name", ""),
        }

    # "idXXX" → числовой
    if q.lower().startswith("id") and q[2:].isdigit():
        return _resolve_vk_user(q[2:])

    # Иначе считаем, что это screen_name
    try:
        res = vk.users.get(user_ids=q)
    except Exception:
        logger.exception("_resolve_vk_user: vk.users.get(screen) ошибка")
        return None
    if not res:
        return None
    u = res[0]
    return {
        "id":          int(u["id"]),
        "name":        f"{u.get('first_name','').strip()} "
                       f"{u.get('last_name','').strip()}".strip()
                       or f"VK-{u['id']}",
        "screen_name": u.get("screen_name", q),
    }


def _vk_user_id_from_forward(raw_message: dict) -> Optional[int]:
    """
    Извлечь from_id из forward'нутого или reply сообщения, если оно есть.
    raw_message — словарь VK-сообщения (event["raw"]).
    """
    if not isinstance(raw_message, dict):
        return None
    # reply_message: одиночный ответ
    reply = raw_message.get("reply_message")
    if isinstance(reply, dict):
        fid = reply.get("from_id")
        if isinstance(fid, int) and fid > 0:
            return fid
    # fwd_messages: список пересланных
    fwd = raw_message.get("fwd_messages")
    if isinstance(fwd, list):
        for m in fwd:
            if isinstance(m, dict):
                fid = m.get("from_id")
                if isinstance(fid, int) and fid > 0:
                    return fid
    return None


# ─── 1. НАЙМ ────────────────────────────────────────────────────────

@on_text(B.BTN_HIRE_COURIER)
def admin_hire_courier_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    admin_state[user_id] = {"action": "hire_input"}
    safe_send(
        peer_id,
        "➕ Найм Доставщика\n\n"
        "Пришлите одним сообщением ОДИН из вариантов:\n\n"
        "1️⃣ Ссылку на профиль:\n"
        "   vk.com/id12345  или  vk.com/durov\n\n"
        "2️⃣ Числовой VK-ID или screen_name:\n"
        "   12345  или  durov\n\n"
        "3️⃣ Перешлите (forward) сообщение от Доставщика — "
        "VK-ID возьмём из пересылки автоматически.\n\n"
        "⚠️ Прежде чем нанимать, Доставщик должен хотя бы раз написать "
        "сообществу — иначе бот не сможет ему писать.\n\n"
        "Отправьте «отмена», чтобы прервать.",
    )


def _is_hire_input(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "hire_input")


@on_state(_is_hire_input)
def hire_input_router(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    courier_id: Optional[int] = None
    courier_info: Optional[dict] = None

    # 1) Forward / reply — приоритет
    fwd_id = _vk_user_id_from_forward(event.get("raw"))
    if fwd_id:
        courier_id = fwd_id
    elif text:
        # 2) Парсим как ссылку/screen/ID — но это лишь резолв имени;
        # main id мы и так получим из ответа vk.users.get
        info = _resolve_vk_user(text)
        if info is None:
            safe_send(peer_id,
                      "⚠️ Не удалось найти такого пользователя VK.\n"
                      "Проверьте ссылку/ID и попробуйте ещё раз "
                      "(или отправьте «отмена»).")
            return
        courier_id   = info["id"]
        courier_info = info
    else:
        safe_send(peer_id,
                  "⚠️ Нужно прислать текст или forward от Доставщика.")
        return

    # Если мы получили id из forward, тоже подтянем имя
    if courier_info is None and courier_id is not None:
        courier_info = _resolve_vk_user(str(courier_id))
        if courier_info is None:
            courier_info = {"id": courier_id, "name": f"VK-{courier_id}",
                            "screen_name": ""}

    # Не разрешаем нанимать админа
    if courier_id == config.ADMIN_VK_ID:
        safe_send(peer_id, "⚠️ Нельзя нанять администратора как Доставщика.")
        return

    # Проверка, не нанят ли уже
    try:
        existing = db.get_courier_by_chat_id(courier_id)
    except Exception:
        existing = None
    if existing:
        admin_state.pop(user_id, None)
        safe_send(
            peer_id,
            f"ℹ️ Этот пользователь уже работает Доставщиком:\n"
            f"👤 {existing['name']}\n"
            f"🆔 {courier_id}\n"
            f"📞 {existing['payment_phone'] or 'номер не указан'}",
        )
        return

    # Переходим к вводу телефона
    admin_state[user_id] = {
        "action":       "hire_phone",
        "courier_id":   courier_id,
        "courier_name": courier_info["name"],
        "screen_name":  courier_info.get("screen_name", ""),
    }
    safe_send(
        peer_id,
        f"📋 Найдено:\n"
        f"👤 {courier_info['name']}\n"
        f"🆔 {courier_id}\n"
        f"🔗 vk.com/{courier_info.get('screen_name') or f'id{courier_id}'}\n\n"
        f"📞 Введите номер телефона Доставщика для переводов "
        f"(10–15 цифр), или отправьте «пропустить», чтобы оставить пустым.",
    )


def _is_hire_phone(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "hire_phone")


@on_state(_is_hire_phone)
def hire_phone_router(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = admin_state.get(user_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    phone: Optional[str] = None
    if text.lower() in ("пропустить", "skip", "-"):
        phone = None
    else:
        phone = normalize_phone(text)
        if phone is None:
            safe_send(peer_id,
                      "⚠️ Неверный формат. Должно быть 10–15 цифр.\n"
                      "Попробуйте ещё раз или отправьте «пропустить» / «отмена».")
            return

    courier_id   = state["courier_id"]
    courier_name = state["courier_name"]

    try:
        db.add_courier(courier_name, courier_id, phone)
        db.log_user_action(user_id, f"hired_courier:{courier_id}")
    except Exception:
        logger.exception("hire_phone_router: ошибка add_courier")
        admin_state.pop(user_id, None)
        safe_send(peer_id, "⚠️ Не удалось сохранить Доставщика в БД.")
        return

    admin_state.pop(user_id, None)
    safe_send(
        peer_id,
        f"✅ Доставщик нанят!\n"
        f"👤 {courier_name}\n"
        f"🆔 {courier_id}\n"
        f"📞 {phone or 'не указан'}\n\n"
        f"ℹ️ Если бот ещё не может писать ему — попросите его написать "
        f"что-нибудь сообществу.",
    )

    # Опционально — уведомим самого курьера, что его наняли (если бот может)
    safe_send(
        courier_id,
        "🎉 Поздравляем! Вы добавлены как Доставщик.\n"
        "Откройте главное меню — у вас появились кнопки «📊 Мой отчёт», "
        "«📋 Неоплаченные заказы» и «📞 Мой номер для переводов».",
        keyboard=build_main_menu_keyboard(courier_id),
    )


# ─── 2. УВОЛИТЬ ─────────────────────────────────────────────────────

COURIERS_PER_PAGE_ADMIN = 5   # 5 + 1 ряд пагинации = 6 рядов


def _send_couriers_list_for_action(peer_id: int, *, cb_command: str,
                                   title: str, label_prefix: str,
                                   color: str,
                                   page: int = 0,
                                   conversation_message_id: Optional[int] = None) -> bool:
    """
    Универсальный список курьеров для действия (fire / edit_phone).
    Возвращает True, если есть кому показывать.
    """
    try:
        couriers = db.get_all_couriers_with_phones()
    except Exception:
        logger.exception("_send_couriers_list_for_action: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка загрузки списка.")
        return False
    if not couriers:
        safe_send(peer_id, "Список Доставщиков пуст.")
        return False

    total_pages = max(1, (len(couriers) + COURIERS_PER_PAGE_ADMIN - 1)
                         // COURIERS_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * COURIERS_PER_PAGE_ADMIN
    page_couriers = couriers[start:start + COURIERS_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for c in page_couriers:
        phone = c["payment_phone"] or "—"
        label = f"{label_prefix}{c['name']} · {phone}"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": cb_command, "c": c["telegram_chat_id"]},
            color=color,
        ))

    if total_pages > 1:
        nav = []
        nav_cmd = cb_command + "_page"
        if page > 0:
            nav.append(B.callback_button(
                "◀", {"command": nav_cmd, "p": page - 1}))
        nav.append(B.callback_button(
            f"{page + 1}/{total_pages}",
            {"command": "noop"},
            color=B.COLOR_SECONDARY,
        ))
        if page < total_pages - 1:
            nav.append(B.callback_button(
                "▶", {"command": nav_cmd, "p": page + 1}))
        kb.row(*nav)

    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, title, keyboard=kb.dump()):
            return True
    safe_send(peer_id, title, keyboard=kb.dump())
    return True


@on_text(B.BTN_FIRE_COURIER)
def admin_fire_courier(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    _send_couriers_list_for_action(
        peer_id,
        cb_command="fire",
        title="❌ Кого уволить?",
        label_prefix="❌ ",
        color=B.COLOR_NEGATIVE,
    )


@on_callback("fire_page")
def cb_fire_page(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _send_couriers_list_for_action(
        peer_id, cb_command="fire",
        title="❌ Кого уволить?",
        label_prefix="❌ ",
        color=B.COLOR_NEGATIVE,
        page=page,
        conversation_message_id=cmid,
    )
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("fire")
def cb_fire_confirm(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        courier_id = int(payload["c"])
        courier = db.get_courier_by_chat_id(courier_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not courier:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не найден"})
        return

    text = (f"⚠️ Уволить Доставщика?\n\n"
            f"👤 {courier['name']}\n"
            f"🆔 {courier_id}\n"
            f"📞 {courier['payment_phone'] or '—'}")
    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("✅ Да, уволить",
                          {"command": "fire_do", "c": courier_id},
                          color=B.COLOR_NEGATIVE),
        B.callback_button("⛔ Отмена",
                          {"command": "fire_cancel"},
                          color=B.COLOR_SECONDARY),
    )
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("fire_do")
def cb_fire_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        courier_id = int(payload["c"])
        courier = db.get_courier_by_chat_id(courier_id)
        if not courier:
            send_event_answer(event["event_id"], user_id, peer_id,
                              {"type": "show_snackbar", "text": "Не найден"})
            return
        name = courier["name"]
        n = db.delete_courier_by_name(name)
        if n:
            db.log_user_action(user_id, f"fired_courier:{courier_id}")
    except Exception:
        logger.exception("cb_fire_do: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка"})
        return

    text = (f"✅ Доставщик «{name}» уволен."
            if n else f"Доставщик не найден.")
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar",
                       "text": "Уволен" if n else "Не найден"})


@on_callback("fire_cancel")
def cb_fire_cancel(event, payload):
    cmid = event.get("conversation_message_id")
    if cmid is None or not edit_message(event["peer_id"], cmid, "Отменено."):
        safe_send(event["peer_id"], "Отменено.")
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


# ─── 3. ИЗМЕНИТЬ НОМЕР КУРЬЕРА ──────────────────────────────────────

@on_text(B.BTN_EDIT_COURIER_PHONE)
def admin_edit_courier_phone_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    _send_couriers_list_for_action(
        peer_id,
        cb_command="ecph",
        title="📱 Выберите Доставщика для изменения номера:",
        label_prefix="📱 ",
        color=B.COLOR_PRIMARY,
    )


@on_callback("ecph_page")
def cb_ecph_page(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _send_couriers_list_for_action(
        peer_id, cb_command="ecph",
        title="📱 Выберите Доставщика для изменения номера:",
        label_prefix="📱 ",
        color=B.COLOR_PRIMARY,
        page=page,
        conversation_message_id=cmid,
    )
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("ecph")
def cb_ecph_select(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        courier_id = int(payload["c"])
        courier = db.get_courier_by_chat_id(courier_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not courier:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не найден"})
        return

    admin_state[user_id] = {
        "action":       "edit_courier_phone",
        "courier_id":   courier_id,
        "courier_name": courier["name"],
    }
    current = courier["payment_phone"] or "не указан"
    text = (
        f"📱 Изменение номера для переводов\n"
        f"👤 {courier['name']}\n"
        f"📞 Текущий: {current}\n\n"
        f"Введите новый номер (10–15 цифр), например 79123456789.\n"
        f"Или отправьте «удалить», чтобы стереть номер.\n"
        f"Отправьте «отмена», чтобы прервать."
    )
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_admin_editing_courier_phone(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "edit_courier_phone")


@on_state(_is_admin_editing_courier_phone)
def admin_edit_courier_phone_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = admin_state.get(user_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    courier_id   = state["courier_id"]
    courier_name = state["courier_name"]

    if text.lower() in ("удалить", "delete", "-"):
        try:
            db.update_courier_phone(courier_id, "")
            db.log_user_action(user_id, f"cleared_courier_phone:{courier_id}")
        except Exception:
            logger.exception("admin_edit_courier_phone_apply: clear")
            admin_state.pop(user_id, None)
            safe_send(peer_id, "⚠️ Не удалось обновить.")
            return
        admin_state.pop(user_id, None)
        safe_send(peer_id, f"✅ Номер у «{courier_name}» стёрт.")
        return

    phone = normalize_phone(text)
    if phone is None:
        safe_send(peer_id,
                  "⚠️ Неверный формат. Должно быть 10–15 цифр.\n"
                  "Попробуйте ещё раз или отправьте «отмена» / «удалить».")
        return

    try:
        db.update_courier_phone(courier_id, phone)
        db.log_user_action(user_id, f"updated_courier_phone:{courier_id}")
    except Exception:
        logger.exception("admin_edit_courier_phone_apply: ошибка БД")
        admin_state.pop(user_id, None)
        safe_send(peer_id, "⚠️ Не удалось обновить.")
        return

    admin_state.pop(user_id, None)
    safe_send(peer_id,
              f"✅ Номер для переводов Доставщика «{courier_name}» обновлён:\n{phone}")


# ─── 4. СПИСОК ДОСТАВЩИКОВ ──────────────────────────────────────────

@on_text(B.BTN_COURIER_LIST)
def admin_list_couriers(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        couriers = db.get_all_couriers_with_phones()
    except Exception:
        logger.exception("admin_list_couriers: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return
    if not couriers:
        safe_send(peer_id, "Список Доставщиков пуст.")
        return

    lines = ["📋 Список Доставщиков:\n"]
    for c in couriers:
        phone = c["payment_phone"] or "❌ не указан"
        lines.append(f"👤 {c['name']}\n"
                     f"🆔 {c['telegram_chat_id']}\n"
                     f"📞 {phone}\n"
                     f"{'─' * 25}")
    text = "\n".join(lines)
    # Разбиваем по 4000 символов (лимит VK — 4096)
    for chunk_start in range(0, len(text), 4000):
        safe_send(peer_id, text[chunk_start:chunk_start + 4000])


# ─── 5. НАЙТИ VK-ID ПО НОМЕРУ ЗАКАЗА ────────────────────────────────

@on_text(B.BTN_FIND_CHAT_ID)
def admin_find_chat_id_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    admin_state[user_id] = {"action": "find_chat_id"}
    safe_send(peer_id,
              "🆔 Введите номер заказа.\n"
              "Отправьте «отмена», чтобы прервать.")


def _is_finding_chat_id(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "find_chat_id")


@on_state(_is_finding_chat_id)
def admin_find_chat_id_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    admin_state.pop(user_id, None)
    try:
        uid = db.get_user_id_by_order_number(text)
    except Exception:
        logger.exception("admin_find_chat_id_apply: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if uid:
        safe_send(peer_id,
                  f"VK-ID клиента по заказу {text}:\n"
                  f"🆔 {uid}\n"
                  f"🔗 vk.com/id{uid}")
    else:
        safe_send(peer_id, "Заказ не найден.")


# ─── 6. РАССЫЛКА ДОСТАВЩИКАМ ────────────────────────────────────────

@on_text(B.BTN_MSG_COURIERS)
def admin_msg_couriers_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    admin_state[user_id] = {"action": "msg_couriers"}
    safe_send(peer_id,
              "📩 Введите сообщение для всех Доставщиков.\n"
              "Отправьте «отмена», чтобы прервать.")


def _is_msg_couriers(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "msg_couriers")


@on_state(_is_msg_couriers)
def admin_msg_couriers_send(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return
    if not text:
        safe_send(peer_id, "⚠️ Пустое сообщение. Введите текст или «отмена».")
        return

    admin_state.pop(user_id, None)

    body = f"👤 Админ:\n{text}"
    try:
        chat_ids = db.get_all_courier_chat_ids()
    except Exception:
        logger.exception("admin_msg_couriers_send: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    sent = 0
    failed = 0
    for cid in chat_ids:
        if safe_send(cid, body) is not None:
            sent += 1
        else:
            failed += 1

    safe_send(peer_id,
              f"📨 Рассылка завершена.\n"
              f"✅ Доставлено: {sent}\n"
              f"❌ Не доставлено: {failed}")
    try:
        db.log_user_action(user_id, f"msg_couriers:{sent}/{sent+failed}")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 8: ЧАТЫ И ПОДДЕРЖКА
#
#   - "📩 Чат с доставщиком": клиент пишет → курьер получает с кнопкой
#     "💬 Ответить" → курьер пишет → клиент получает.
#     Перенесено 1-в-1 из Telegram-версии.
#
#   - "💡 Поддержка и помощь": FAQ + кнопка связи с админом.
#     В VK два варианта:
#       a) если ADMIN_VK_SCREEN задан в .env → ссылка vk.me/<screen>
#       b) иначе — внутренний канал поддержки: юзер пишет боту, бот
#          форвардит админу с callback "Ответить", админ отвечает,
#          бот доставляет юзеру.
#
#   Состояния:
#     - chat_to_courier_state[user_id] — ждём текст сообщения для курьера
#     - reply_state[user_id] — ждём текст ответа (общая для курьера и админа)
#         {"target_id": <user_id>, "target_name": "...", "role": "courier"|"admin"}
#     - support_state[user_id] — ждём текст вопроса в поддержку
# ════════════════════════════════════════════════════════════════════

# Состояния FSM
chat_to_courier_state: set[int] = set()   # user_id, ожидающие ввода текста курьеру
reply_state:           dict[int, dict] = {}   # who → {target_id, target_name, role}


# ─── Хелпер: вырезаем имя пользователя ──────────────────────────────

def _safe_display_name(user_id: int, fallback_prefix: str = "Клиент") -> str:
    """Получить имя пользователя из БД или сформировать дефолтное."""
    try:
        pii = db.get_user_pii(user_id)
        name = pii.get("name") if pii else None
        if name:
            return name
    except Exception:
        pass
    return f"{fallback_prefix} #{user_id}"


# ════════════════════════════════════════════════════════════════════
#   1. ЧАТ С КУРЬЕРОМ (клиент → курьер)
# ════════════════════════════════════════════════════════════════════

@on_text(B.BTN_CHAT_COURIER)
def chat_to_courier_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    try:
        courier_id = db.get_user_preferred_courier(user_id)
    except Exception:
        logger.exception("chat_to_courier_start: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось загрузить данные. Попробуйте позже.")
        return
    if not courier_id:
        safe_send(peer_id,
                  "⚠️ Сначала выберите Доставщика (🚴 в главном меню).")
        return

    chat_to_courier_state.add(user_id)
    safe_send(peer_id,
              "✉ Введите одно сообщение для Доставщика.\n"
              "Отправьте «отмена», чтобы прервать.")


def _is_chat_to_courier(user_id: int, _text: str) -> bool:
    return user_id in chat_to_courier_state


@on_state(_is_chat_to_courier)
def chat_to_courier_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        chat_to_courier_state.discard(user_id)
        safe_send(peer_id, "Отменено.")
        return

    if not text:
        safe_send(peer_id, "⚠️ Пустое сообщение. Введите текст или «отмена».")
        return

    if len(text) > 2000:
        safe_send(peer_id, "⚠️ Слишком длинно (макс. 2000 символов).")
        return

    chat_to_courier_state.discard(user_id)

    try:
        courier_id = db.get_user_preferred_courier(user_id)
    except Exception:
        logger.exception("chat_to_courier_apply: ошибка БД")
        courier_id = None
    if not courier_id:
        safe_send(peer_id, "⚠️ Не удалось определить Доставщика. Выберите его заново.")
        return

    name = _safe_display_name(user_id, "Клиент")
    # Сохраняем для возможного ответа курьера
    user_last_messages[user_id] = {"name": name, "vk_id": user_id}

    # Сообщение курьеру с кнопкой "Ответить"
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("💬 Ответить",
                             {"command": "reply_to_user", "u": user_id},
                             color=B.COLOR_PRIMARY))

    msg = (f"✉ Сообщение от клиента «{name}» (VK-ID: {user_id}):\n\n"
           f"{text}")
    cmid = safe_send(courier_id, msg, keyboard=kb.dump())
    if cmid is None:
        safe_send(peer_id,
                  "⚠️ Не удалось доставить сообщение Доставщику. "
                  "Попробуйте позже.")
        return

    safe_send(peer_id, "✅ Сообщение отправлено Доставщику.")
    try:
        db.log_user_action(user_id, f"chat_to_courier:{courier_id}")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#   2. ОТВЕТ КУРЬЕРА КЛИЕНТУ (callback "💬 Ответить")
#
#   Единый механизм reply_state используется как курьером, так и админом
#   (когда отвечает на сообщение поддержки).
# ════════════════════════════════════════════════════════════════════

@on_callback("reply_to_user")
def cb_reply_to_user(event, payload):
    """Курьер нажал «💬 Ответить»."""
    courier_id = event["from_id"]
    peer_id    = event["peer_id"]
    cmid       = event.get("conversation_message_id")
    try:
        target_user_id = int(payload["u"])
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], courier_id, peer_id)
        return

    # Имя клиента — из user_last_messages или из БД
    info = user_last_messages.get(target_user_id) or {}
    target_name = info.get("name") or _safe_display_name(target_user_id, "Клиент")

    reply_state[courier_id] = {
        "target_id":   target_user_id,
        "target_name": target_name,
        "role":        "courier",
    }

    safe_send(peer_id,
              f"✍ Введите ответ для «{target_name}».\n"
              f"Отправьте «отмена», чтобы прервать.")

    # Снимаем кнопку «Ответить» с исходного сообщения, чтобы не было соблазна
    # нажимать её повторно (только для информации курьеру).
    if cmid is not None:
        edit_message(peer_id, cmid,
                     f"✉ Сообщение от клиента «{target_name}» (отвечено).")

    send_event_answer(event["event_id"], courier_id, peer_id)


def _is_in_reply_state(user_id: int, _text: str) -> bool:
    return user_id in reply_state


@on_state(_is_in_reply_state)
def apply_reply(event):
    """Любой пользователь в reply_state — пишет ответ для своей цели."""
    sender_id = event["from_id"]
    peer_id   = event["peer_id"]
    text      = (event["text"] or "").strip()
    state     = reply_state.get(sender_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        reply_state.pop(sender_id, None)
        safe_send(peer_id, "Отменено.")
        return

    if not text:
        safe_send(peer_id, "⚠️ Пустое сообщение. Введите текст или «отмена».")
        return

    if len(text) > 2000:
        safe_send(peer_id, "⚠️ Слишком длинно (макс. 2000 символов).")
        return

    target_id   = state.get("target_id")
    target_name = state.get("target_name", "Пользователь")
    role        = state.get("role", "courier")

    if not target_id:
        reply_state.pop(sender_id, None)
        safe_send(peer_id, "⚠️ Не удалось определить адресата. Попробуйте заново.")
        return

    reply_state.pop(sender_id, None)

    # Формируем подпись
    if role == "courier":
        prefix = "🚴 Ответ Доставщика:"
    elif role == "admin":
        prefix = "👤 Ответ администратора:"
    else:
        prefix = "💬 Ответ:"

    if safe_send(target_id, f"{prefix}\n\n{text}") is None:
        safe_send(peer_id, "⚠️ Не удалось доставить ответ. Возможно, пользователь "
                            "запретил сообщения от сообщества.")
        return

    safe_send(peer_id, f"✅ Ответ отправлен «{target_name}».")
    try:
        db.log_user_action(sender_id, f"reply_to:{target_id}")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#   3. ПОДДЕРЖКА: FAQ + связь с админом
# ════════════════════════════════════════════════════════════════════

_FAQ_TEXT = (
    "💡 Поддержка и помощь\n\n"
    "Частые вопросы:\n\n"
    "❓ Как сделать заказ?\n"
    "Нажмите «📋 Смотреть меню» → выберите блюда → «🛒 Открыть корзину» → "
    "«✅ Подтвердить заказ».\n\n"
    "❓ Как оплатить заказ?\n"
    "В корзине нажмите «💳 Выбрать оплату» — доступны перевод и наличные.\n\n"
    "❓ Где мой заказ?\n"
    "Нажмите «📦 Мои заказы» — там виден статус всех ваших заказов.\n\n"
    "❓ Как связаться с Доставщиком?\n"
    "Нажмите «📩 Чат с доставщиком» и напишите сообщение.\n\n"
    "❓ Как изменить адрес доставки?\n"
    "Нажмите «🏠 Сменить адрес» и введите новый адрес.\n\n"
    "❓ Не нашли ответ?\n"
    "Нажмите кнопку ниже, чтобы написать администратору."
)


@on_text(B.BTN_SUPPORT)
def support_faq(event):
    """FAQ + кнопка для связи с админом."""
    peer_id = event["peer_id"]

    kb = B.Keyboard(inline=True)
    admin_screen = (config.ADMIN_VK_SCREEN or "").strip()
    if admin_screen:
        # Внешняя ссылка — открывает диалог с админом в VK напрямую
        kb.row(B.link_button("📝 Написать в поддержку",
                             f"https://vk.me/{admin_screen.lstrip('@')}"))
    else:
        # Внутренний канал: юзер пишет боту, бот форвардит админу
        kb.row(B.callback_button("📝 Написать в поддержку (через бот)",
                                 {"command": "support_start"},
                                 color=B.COLOR_PRIMARY))
    kb.row(B.callback_button("❌ Закрыть",
                             {"command": "faq_close"},
                             color=B.COLOR_SECONDARY))

    safe_send(peer_id, _FAQ_TEXT, keyboard=kb.dump())


@on_callback("faq_close")
def cb_faq_close(event, payload):
    cmid = event.get("conversation_message_id")
    if cmid is not None:
        delete_message(event["peer_id"], cmid)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


@on_callback("support_start")
def cb_support_start(event, payload):
    """Пользователь хочет написать в поддержку через бот (внутренний канал)."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    support_state[user_id] = {"step": "awaiting_question"}

    text = (
        "📝 Опишите вашу проблему одним сообщением.\n"
        "Администратор ответит вам как сможет.\n\n"
        "Отправьте «отмена», чтобы прервать."
    )
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_writing_support(user_id: int, _text: str) -> bool:
    state = support_state.get(user_id)
    return bool(state and state.get("step") == "awaiting_question")


@on_state(_is_writing_support)
def support_send_to_admin(event):
    """Юзер написал вопрос — пересылаем админу с кнопкой «Ответить»."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        support_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    if not text:
        safe_send(peer_id, "⚠️ Пустое сообщение. Введите текст или «отмена».")
        return

    if len(text) > 2000:
        safe_send(peer_id, "⚠️ Слишком длинно (макс. 2000 символов).")
        return

    support_state.pop(user_id, None)

    name = _safe_display_name(user_id, "Клиент")
    # Сохраняем для callback "Ответить"
    user_last_messages[user_id] = {"name": name, "vk_id": user_id}

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("💬 Ответить",
                             {"command": "admin_reply_to", "u": user_id},
                             color=B.COLOR_PRIMARY))

    body = (
        f"📨 Обращение в поддержку\n"
        f"От: «{name}» (VK-ID: {user_id})\n"
        f"🔗 vk.com/id{user_id}\n\n"
        f"{text}"
    )
    cmid = safe_send(config.ADMIN_VK_ID, body, keyboard=kb.dump())
    if cmid is None:
        safe_send(peer_id, "⚠️ Не удалось доставить сообщение. Попробуйте позже.")
        return

    safe_send(peer_id, "✅ Ваше сообщение отправлено администратору. "
                       "Ответ придёт в этот чат.")
    try:
        db.log_user_action(user_id, "support_ticket")
    except Exception:
        pass


@on_callback("admin_reply_to")
def cb_admin_reply_to(event, payload):
    """Админ нажал «Ответить» на тикет поддержки."""
    admin_id = event["from_id"]
    peer_id  = event["peer_id"]
    cmid     = event.get("conversation_message_id")

    if not is_admin(admin_id):
        send_event_answer(event["event_id"], admin_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет прав"})
        return

    try:
        target_user_id = int(payload["u"])
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], admin_id, peer_id)
        return

    info = user_last_messages.get(target_user_id) or {}
    target_name = info.get("name") or _safe_display_name(target_user_id, "Клиент")

    reply_state[admin_id] = {
        "target_id":   target_user_id,
        "target_name": target_name,
        "role":        "admin",
    }

    safe_send(peer_id,
              f"✍ Введите ответ для «{target_name}».\n"
              f"Отправьте «отмена», чтобы прервать.")

    if cmid is not None:
        edit_message(peer_id, cmid,
                     f"📨 Обращение от «{target_name}» (отвечено).")

    send_event_answer(event["event_id"], admin_id, peer_id)


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 9: МОИ ЗАКАЗЫ И ИСТОРИЯ
#
#   - "📦 Мои заказы": последние 10 — список с inline-кнопками для деталей.
#   - "📜 История заказов": выбор формата (текст / TXT-файл / DOCX-файл)
#     и до 1000 заказов выгружается.
#
#   Отличия от Telegram:
#   - Документы в VK загружаются через VkUpload.document_message (3-шаговый
#     upload: get_server → POST файла → docs.save). Делает наш send_document().
#   - Markdown отсутствует → форматирование plain text + эмодзи.
# ════════════════════════════════════════════════════════════════════

ORDERS_TO_SHOW          = 50    # сколько заказов всего тянем для пагинации
ORDERS_PAGE_SIZE        = 5     # 5 кнопок-деталей на странице
HISTORY_LIMIT  = 1000         # сколько заказов выгружает "📜 История"


def _format_order_status_emoji(status: str) -> str:
    """Подобрать эмодзи для статуса заказа."""
    s = (status or "").lower()
    if "достав" in s and "не" not in s:
        return "✅"
    if "принят" in s:
        return "🚴"
    if "отмен" in s:
        return "❌"
    if "wait" in s or "ожид" in s:
        return "⏳"
    return "📋"


# ─── "📦 Мои заказы" — компактный список с инлайн-деталями ──────────

@on_text(B.BTN_MY_ORDERS)
def my_orders(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    _send_my_orders_page(peer_id, user_id, page=0)


@on_callback("myo_page")
def cb_myo_page(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _send_my_orders_page(peer_id, user_id, page=page,
                         conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


def _send_my_orders_page(peer_id: int, user_id: int, page: int = 0,
                        *, conversation_message_id: Optional[int] = None) -> None:
    try:
        orders = db.get_user_orders(user_id, limit=ORDERS_TO_SHOW)
    except Exception:
        logger.exception("_send_my_orders_page: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось загрузить заказы.")
        return

    if not orders:
        safe_send(peer_id,
                  "📦 У вас пока нет заказов.\n\n"
                  "Чтобы начать — нажмите «📋 Смотреть меню».")
        return

    total_pages = max(1, (len(orders) + ORDERS_PAGE_SIZE - 1) // ORDERS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * ORDERS_PAGE_SIZE
    page_orders = orders[start:start + ORDERS_PAGE_SIZE]

    lines = [f"📦 Ваши заказы (стр. {page + 1}/{total_pages}):\n"]
    for o in page_orders:
        emo = _format_order_status_emoji(o["status"])
        lines.append(
            f"{emo} {o['order_number']}\n"
            f"   💰 {fmt_money(o['total_price'])} ₽ · {o['status']}"
        )

    text = "\n\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…(список обрезан)"

    kb = B.Keyboard(inline=True)
    for o in page_orders:
        label = f"📋 {o['order_number']}"[:B.MAX_LABEL_LEN]
        kb.row(B.callback_button(
            label,
            {"command": "order_details", "o": o["order_number"], "p": page},
            color=B.COLOR_PRIMARY,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "myo_page", "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "myo_page", "p": page + 1}))
        kb.row(*nav)

    if conversation_message_id is not None and edit_message(
            peer_id, conversation_message_id, text, keyboard=kb.dump()):
        return
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("order_details")
def cb_order_details(event, payload):
    """Карточка одного заказа с составом."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    order_number = payload.get("o")
    if not order_number:
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        order = db.get_order(order_number)
    except Exception:
        logger.exception("cb_order_details: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not order:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Заказ не найден"})
        return

    # Только владелец видит свой заказ
    if order["user_id"] != user_id and not is_admin(user_id):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Чужой заказ"})
        return

    emo = _format_order_status_emoji(order["status"])
    text = (
        f"{emo} Заказ {order_number}\n"
        f"📅 Создан: {order['created_at']}\n"
        f"💰 Сумма: {fmt_money(order['total_price'])} ₽\n"
        f"💳 Оплата: {order['payment_method']}\n"
        f"📊 Статус: {order['status']}"
    )
    if order["comment"]:
        text += f"\n📝 Комментарий: {order['comment']}"

    # Кнопка возврата на страницу со списком заказов
    try:
        back_page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        back_page = 0
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("⬅ К списку",
                             {"command": "myo_page", "p": back_page},
                             color=B.COLOR_SECONDARY))

    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


# ─── "📜 История заказов" — выбор формата → выгрузка ────────────────

# Состояние выбора формата
history_state: set[int] = set()


@on_text(B.BTN_ORDER_HISTORY)
def order_history_ask_format(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    # Сначала проверим, есть ли заказы вообще
    try:
        orders = db.get_user_orders(user_id, limit=1)
    except Exception:
        logger.exception("order_history_ask_format: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось загрузить заказы.")
        return
    if not orders:
        safe_send(peer_id, "📜 У вас пока нет заказов.")
        return

    history_state.add(user_id)
    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("📄 В чате (текст)",
                             {"command": "hist_fmt", "f": "inline"},
                             color=B.COLOR_PRIMARY))
    kb.row(B.callback_button("📃 TXT файл",
                             {"command": "hist_fmt", "f": "txt"},
                             color=B.COLOR_SECONDARY))
    kb.row(B.callback_button("📑 DOCX файл",
                             {"command": "hist_fmt", "f": "docx"},
                             color=B.COLOR_SECONDARY))
    kb.row(B.callback_button("❌ Отмена",
                             {"command": "hist_cancel"},
                             color=B.COLOR_NEGATIVE))
    safe_send(peer_id,
              "📜 В каком виде получить историю заказов?",
              keyboard=kb.dump())


@on_callback("hist_cancel")
def cb_hist_cancel(event, payload):
    history_state.discard(event["from_id"])
    cmid = event.get("conversation_message_id")
    if cmid is None or not edit_message(event["peer_id"], cmid, "Отменено."):
        safe_send(event["peer_id"], "Отменено.")
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


@on_callback("hist_fmt")
def cb_hist_fmt(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    fmt = payload.get("f")

    history_state.discard(user_id)

    if fmt not in ("inline", "txt", "docx"):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        orders = db.get_user_orders(user_id, limit=HISTORY_LIMIT)
    except Exception:
        logger.exception("cb_hist_fmt: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if not orders:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет заказов"})
        return

    # Уберём экран выбора
    if cmid is not None:
        delete_message(peer_id, cmid)

    if fmt == "inline":
        _send_history_inline(peer_id, orders)
    elif fmt == "txt":
        _send_history_txt(peer_id, user_id, orders)
    elif fmt == "docx":
        _send_history_docx(peer_id, user_id, orders)

    try:
        db.log_user_action(user_id, f"history_export:{fmt}:{len(orders)}")
    except Exception:
        pass

    send_event_answer(event["event_id"], user_id, peer_id)


def _send_history_inline(peer_id: int, orders: list) -> None:
    """Прислать историю одним или несколькими сообщениями в чат."""
    lines = ["📜 История заказов:\n"]
    for o in orders:
        emo = _format_order_status_emoji(o["status"])
        lines.append(
            f"{emo} {o['order_number']}\n"
            f"   📅 {o['created_at']}\n"
            f"   💰 {fmt_money(o['total_price'])} ₽ · {o['status']}"
        )

    text = "\n\n".join(lines)
    # VK лимит сообщения 4096 — режем чанками по 4000
    chunk_size = 4000
    if len(text) <= chunk_size:
        safe_send(peer_id, text)
        return

    chunks = []
    cur = ""
    for line in text.split("\n\n"):
        candidate = cur + ("\n\n" if cur else "") + line
        if len(candidate) > chunk_size:
            chunks.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        chunks.append(cur)

    for ch in chunks:
        safe_send(peer_id, ch)


def _send_history_txt(peer_id: int, user_id: int, orders: list) -> None:
    """Сохранить в TXT и отправить как документ."""
    from utils import temporary_file
    with temporary_file(prefix=f"history_{user_id}_", suffix=".txt") as tmp_file:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write("История заказов\n")
            f.write("=" * 50 + "\n\n")
            for o in orders:
                f.write(f"Заказ {o['order_number']}\n")
                f.write(f"  Создан: {o['created_at']}\n")
                f.write(f"  Сумма:  {o['total_price']} ₽\n")
                f.write(f"  Оплата: {o['payment_method']}\n")
                f.write(f"  Статус: {o['status']}\n")
                if o["comment"]:
                    f.write(f"  Комментарий: {o['comment']}\n")
                f.write("-" * 50 + "\n")
        title = f"history_{user_id}.txt"
        mid = send_document(peer_id, str(tmp_file), title=title,
                            text=f"📜 История заказов ({len(orders)} шт):")
        if mid is None:
            safe_send(peer_id, "⚠️ Не удалось отправить файл. "
                                "Попробуйте формат «В чате (текст)».")


def _send_history_docx(peer_id: int, user_id: int, orders: list) -> None:
    """Сохранить в DOCX и отправить как документ."""
    try:
        from docx import Document
    except ImportError:
        safe_send(peer_id,
                  "⚠️ DOCX недоступен на сервере. "
                  "Попробуйте «TXT» или «В чате (текст)».")
        return
    from utils import temporary_file

    with temporary_file(prefix=f"history_{user_id}_", suffix=".docx") as tmp_file:
        doc = Document()
        doc.add_heading("История заказов", level=1)
        for o in orders:
            doc.add_paragraph(
                f"№{o['order_number']} от {o['created_at']}\n"
                f"Сумма: {o['total_price']} ₽\n"
                f"Оплата: {o['payment_method']}\n"
                f"Статус: {o['status']}"
                + (f"\nКомментарий: {o['comment']}" if o["comment"] else "")
                + "\n" + "—" * 30
            )
        doc.save(str(tmp_file))

        title = f"history_{user_id}.docx"
        mid = send_document(peer_id, str(tmp_file), title=title,
                            text=f"📜 История заказов ({len(orders)} шт):")
        if mid is None:
            safe_send(peer_id, "⚠️ Не удалось отправить файл. "
                                "Попробуйте формат «В чате (текст)».")


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 10: СКИДКИ (админ)
#
#   - "🏷 Скидки": список активных + кнопки Добавить / Убрать / Закрыть
#   - Добавить: категория → блюдо (с пагинацией) → тип (% / ₽) →
#     ввод значения → срок (forever / 1 / 3 / 7 дней)
#   - Убрать: список активных скидок (с пагинацией) → клик удаляет
#
#   FSM в discount_state[user_id]:
#     {"step": "value", "menu_id": ..., "kind": "percent"|"rub"}
#
#   Все ограничения inline VK (≤6 рядов) учтены: блюда по 4/стр.,
#   удаление скидок по 5/стр., 1 ряд навигации.
# ════════════════════════════════════════════════════════════════════

DISCOUNTS_PER_PAGE_VK = 5    # для списка удаления (5 + 1 ряд навигации)


def _fmt_discount_value(d) -> str:
    """Отформатировать значение скидки: '15%' или '50 ₽'.
    Принимает sqlite3.Row или dict — оба поддерживаются.
    Целые значения без '.0'."""
    try:
        kind = d["kind"]
        val  = d["value"]
    except (KeyError, IndexError, TypeError):
        kind, val = None, 0
    # Убираем .0 у целых чисел
    val_str = f"{int(val)}" if float(val).is_integer() else f"{val}"
    if kind == "percent":
        return f"{val_str}%"
    return f"{val_str} ₽"


# ─── Главное меню скидок ────────────────────────────────────────────

@on_text(B.BTN_DISCOUNTS)
def admin_discounts_menu(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return

    try:
        discounts = db.get_all_discounts()
    except Exception:
        logger.exception("admin_discounts_menu: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось загрузить скидки.")
        return

    if discounts:
        lines = ["🏷 Активные скидки:\n"]
        for d in discounts:
            line = f"• {d['name']} — скидка {_fmt_discount_value(d)}"
            if d["valid_until"]:
                line += f" (до {d['valid_until']})"
            lines.append(line)
        text = "\n".join(lines)
    else:
        text = "🏷 Нет активных скидок."

    text += "\n\nВыберите действие:"

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("➕ Добавить скидку",
                             {"command": "disc_add"},
                             color=B.COLOR_POSITIVE))
    if discounts:
        kb.row(B.callback_button("❌ Убрать скидку",
                                 {"command": "disc_rm_list", "p": 0},
                                 color=B.COLOR_NEGATIVE))
    kb.row(B.callback_button("Закрыть",
                             {"command": "disc_close"},
                             color=B.COLOR_SECONDARY))

    # Лимит сообщения 4096 — режем, если много скидок
    if len(text) > 3900:
        text = text[:3890] + "\n…(список обрезан)"

    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("disc_close")
def cb_disc_close(event, payload):
    cmid = event.get("conversation_message_id")
    if cmid is not None:
        delete_message(event["peer_id"], cmid)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


# ─── Добавление скидки: выбор категории ─────────────────────────────

@on_callback("disc_add")
def cb_disc_add(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return

    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0

    kb_str = _build_categories_keyboard_for_admin(
        "disc_cat",
        extra_payload={"p": 0},
        label_prefix="🏷 ",
        page_command="disc_add",   # эта же команда — для смены страницы
        page=page,
    )
    if kb_str is None:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет категорий"})
        return

    # Допишем «Отмена» в конец клавиатуры
    import json as _json
    kb_obj = _json.loads(kb_str)
    kb_obj["buttons"].append([{
        "action": {"type": "callback", "label": "⛔ Отмена",
                   "payload": _json.dumps({"command": "disc_close"})},
        "color": B.COLOR_SECONDARY,
    }])
    kb_str = _json.dumps(kb_obj, ensure_ascii=False)

    text = "🏷 Выберите категорию:"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb_str):
        safe_send(peer_id, text, keyboard=kb_str)
    send_event_answer(event["event_id"], user_id, peer_id)


# ─── Список блюд для назначения скидки ──────────────────────────────

def _send_dishes_for_discount(peer_id: int, category_id: int, page: int,
                              *, conversation_message_id: Optional[int] = None) -> None:
    try:
        cat_name = db.get_category_name(category_id)
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, name, price FROM menu "
                "WHERE category_id = ? AND frozen = 0 ORDER BY name",
                (category_id,))
            items = c.fetchall()
    except Exception:
        logger.exception("_send_dishes_for_discount: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if not items:
        msg = f"В категории «{cat_name}» нет доступных блюд."
        if conversation_message_id is not None:
            edit_message(peer_id, conversation_message_id, msg)
        else:
            safe_send(peer_id, msg)
        return

    total_pages = max(1, (len(items) + DISHES_PER_PAGE_ADMIN - 1) // DISHES_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * DISHES_PER_PAGE_ADMIN
    page_items = items[start:start + DISHES_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for it in page_items:
        # Если у блюда уже есть скидка — пометим звёздочкой
        try:
            cur = db.get_discount(it["id"])
        except Exception:
            cur = None
        marker = "★ " if cur else ""
        label = f"{marker}{it['name']} — {fmt_money(it['price'])} ₽"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": "disc_pick", "d": it["id"]},
            color=B.COLOR_PRIMARY,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "disc_cat", "c": category_id, "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "disc_cat", "c": category_id, "p": page + 1}))
        kb.row(*nav)

    text = (f"🏷 {cat_name}\n"
            f"Выберите блюдо для скидки (★ — уже есть скидка):")
    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb.dump()):
            return
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("disc_cat")
def cb_disc_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    _send_dishes_for_discount(peer_id, category_id, page,
                              conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


# ─── Выбор блюда → тип скидки ───────────────────────────────────────

@on_callback("disc_pick")
def cb_disc_pick(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        menu_id = int(payload["d"])
        dish = db.get_menu_item_by_id(menu_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not dish:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Блюдо не найдено"})
        return

    discount_state[user_id] = {"menu_id": menu_id, "step": "type",
                               "dish_name": dish["name"]}

    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("% Процент",
                          {"command": "disc_kind", "k": "percent"},
                          color=B.COLOR_PRIMARY),
        B.callback_button("₽ Рубли",
                          {"command": "disc_kind", "k": "rub"},
                          color=B.COLOR_PRIMARY),
    )
    kb.row(B.callback_button("⛔ Отмена",
                             {"command": "disc_cancel"},
                             color=B.COLOR_SECONDARY))

    text = (f"🏷 Скидка для блюда:\n"
            f"«{dish['name']}» — {fmt_money(dish['price'])} ₽\n\n"
            f"Тип скидки:")
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("disc_cancel")
def cb_disc_cancel(event, payload):
    user_id = event["from_id"]
    cmid    = event.get("conversation_message_id")
    discount_state.pop(user_id, None)
    if cmid is None or not edit_message(event["peer_id"], cmid, "Отменено."):
        safe_send(event["peer_id"], "Отменено.")
    send_event_answer(event["event_id"], user_id, event["peer_id"])


# ─── Тип выбран → ввод значения ─────────────────────────────────────

@on_callback("disc_kind")
def cb_disc_kind(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return

    state = discount_state.get(user_id)
    if not state:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Начните заново"})
        return

    kind = payload.get("k")
    if kind not in ("percent", "rub"):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    state["kind"] = kind
    state["step"] = "value"

    if kind == "percent":
        prompt = ("Введите размер скидки в процентах (1–99).\n"
                  "Пример: 15\n\n"
                  "Отправьте «отмена», чтобы прервать.")
    else:
        prompt = ("Введите размер скидки в рублях (больше 0).\n"
                  "Пример: 50\n\n"
                  "Отправьте «отмена», чтобы прервать.")

    if cmid is None or not edit_message(peer_id, cmid, prompt):
        safe_send(peer_id, prompt)
    send_event_answer(event["event_id"], user_id, peer_id)


# ─── Ввод значения → выбор срока ────────────────────────────────────

def _is_discount_value_input(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(discount_state.get(user_id), dict)
            and discount_state[user_id].get("step") == "value")


@on_state(_is_discount_value_input)
def discount_value_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = discount_state.get(user_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        discount_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    try:
        value = float(text.replace(",", ".").strip())
    except ValueError:
        safe_send(peer_id, "⚠️ Введите число. Например: 15 или 50.")
        return

    if state["kind"] == "percent":
        if value <= 0 or value > 99:
            safe_send(peer_id, "⚠️ Процент должен быть от 1 до 99.")
            return
    else:  # rub
        if value <= 0:
            safe_send(peer_id, "⚠️ Сумма должна быть больше 0.")
            return
        # Защита от слишком большой скидки
        try:
            dish = db.get_menu_item_by_id(state["menu_id"])
            if dish and value >= dish["price"]:
                safe_send(peer_id,
                          f"⚠️ Скидка {value} ₽ ≥ цены блюда "
                          f"({fmt_money(dish['price'])} ₽). "
                          f"Введите меньшее значение.")
                return
        except Exception:
            pass

    state["value"] = value
    state["step"]  = "duration"

    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("♾ Бессрочно",
                          {"command": "disc_dur", "d": "0"},
                          color=B.COLOR_POSITIVE),
    )
    kb.row(
        B.callback_button("1 день",
                          {"command": "disc_dur", "d": "1"},
                          color=B.COLOR_PRIMARY),
        B.callback_button("3 дня",
                          {"command": "disc_dur", "d": "3"},
                          color=B.COLOR_PRIMARY),
        B.callback_button("7 дней",
                          {"command": "disc_dur", "d": "7"},
                          color=B.COLOR_PRIMARY),
    )
    kb.row(B.callback_button("⛔ Отмена",
                             {"command": "disc_cancel"},
                             color=B.COLOR_SECONDARY))

    safe_send(peer_id,
              f"Размер скидки принят: "
              f"{int(value) if value == int(value) else value}"
              f"{'%' if state['kind'] == 'percent' else ' ₽'}\n\n"
              f"Выберите срок действия:",
              keyboard=kb.dump())


# ─── Срок выбран → сохранение ───────────────────────────────────────

@on_callback("disc_dur")
def cb_disc_duration(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return

    state = discount_state.get(user_id)
    if not state or state.get("step") != "duration":
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Начните заново"})
        return

    try:
        days = int(payload.get("d", 0))
    except (ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    valid_until: Optional[str] = None
    if days > 0:
        from datetime import datetime as _dt, timedelta
        valid_until = (_dt.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        db.set_discount(state["menu_id"], state["kind"], state["value"], valid_until)
        db.log_user_action(user_id, f"discount_set:{state['menu_id']}")
    except Exception:
        logger.exception("cb_disc_duration: ошибка БД")
        discount_state.pop(user_id, None)
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка БД"})
        return

    dish_name = state.get("dish_name", "блюдо")
    val_str = (f"{int(state['value']) if state['value'] == int(state['value']) else state['value']}"
               f"{'%' if state['kind'] == 'percent' else ' ₽'}")
    period_str = "бессрочно" if days == 0 else f"на {days} дн."

    text = f"✅ Скидка установлена!\n«{dish_name}» — {val_str} ({period_str})"

    discount_state.pop(user_id, None)

    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Сохранено"})


# ─── Удаление скидки ────────────────────────────────────────────────

@on_callback("disc_rm_list")
def cb_disc_rm_list(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return

    try:
        discounts = db.get_all_discounts()
    except Exception:
        logger.exception("cb_disc_rm_list: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not discounts:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет скидок"})
        return

    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0

    total_pages = max(1, (len(discounts) + DISCOUNTS_PER_PAGE_VK - 1)
                         // DISCOUNTS_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))
    start = page * DISCOUNTS_PER_PAGE_VK
    page_discounts = discounts[start:start + DISCOUNTS_PER_PAGE_VK]

    kb = B.Keyboard(inline=True)
    for d in page_discounts:
        val_str = _fmt_discount_value(d)
        label = f"❌ {d['name']} ({val_str})"
        if len(label) > B.MAX_LABEL_LEN:
            # Сохраним значение в конце
            suffix = f" ({val_str})"
            avail = B.MAX_LABEL_LEN - len(suffix) - len("❌ ") - 1
            if avail > 5:
                label = f"❌ {d['name'][:avail]}…{suffix}"
            else:
                label = label[:B.MAX_LABEL_LEN]
        kb.row(B.callback_button(
            label,
            {"command": "disc_rm_do", "d": d["menu_id"], "p": page},
            color=B.COLOR_NEGATIVE,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "disc_rm_list", "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "disc_rm_list", "p": page + 1}))
        kb.row(*nav)

    text = "Выберите скидку для удаления:"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("disc_rm_do")
def cb_disc_rm_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        menu_id = int(payload["d"])
        page    = int(payload.get("p", 0))
        db.remove_discount(menu_id)
        db.log_user_action(user_id, f"discount_removed:{menu_id}")
    except Exception:
        logger.exception("cb_disc_rm_do: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Ошибка"})
        return

    # Перерисуем список — если опустел, покажем сообщение
    try:
        discounts = db.get_all_discounts()
    except Exception:
        discounts = []

    if not discounts:
        text = "✅ Скидка удалена.\nБольше активных скидок нет."
        if cmid is None or not edit_message(peer_id, cmid, text):
            safe_send(peer_id, text)
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Удалено"})
        return

    # Иначе — перерисуем список на той же странице
    # Пагинация: если последняя страница опустела — вернёмся назад
    total_pages = max(1, (len(discounts) + DISCOUNTS_PER_PAGE_VK - 1)
                         // DISCOUNTS_PER_PAGE_VK)
    page = max(0, min(page, total_pages - 1))

    cb_disc_rm_list(
        {**event, "conversation_message_id": cmid},
        {"command": "disc_rm_list", "p": page},
    )


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 11: ОТЧЁТЫ + ЦЕНЫ + ПОЛЬЗОВАТЕЛИ + ЗАКАЗЫ + РАССЫЛКА
#
#   Большой блок, который закрывает почти всю оставшуюся админскую часть.
#
#   1. Отчёты (курьер и админ):
#      - выбор периода (Сегодня / Неделя / Месяц / Период / Всё время)
#      - custom-период через FSM 'YYYY-MM-DD YYYY-MM-DD'
#      - Excel-файл через send_document (VkUpload)
#   2. Редактор цен: категория → блюдо → ввод цены
#   3. База пользователей: пагинация, карточка, edit-поля, удаление
#   4. Все заказы: текстом с разбивкой по чанкам
#   5. Рассылка пользователям
#
#   Что отличается от Telegram:
#   - Excel загружается через send_document (3-шаговый upload VK)
#   - Markdown не работает — plain text + эмодзи
#   - Inline-клавиатуры ≤6 рядов: пагинация подобрана везде
# ════════════════════════════════════════════════════════════════════

from datetime import timedelta

USERS_PER_PAGE_VK = 5  # 5 + 1 ряд навигации = 6


# ─── Общие хелперы периода ──────────────────────────────────────────

def _period_keyboard(kind: str) -> str:
    """
    Inline-клавиатура выбора периода. kind: 'adm' или 'cur'.
    Возвращает JSON для keyboard.
    """
    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("📅 Сегодня",
                          {"command": "rep_pick", "k": kind, "p": "today"},
                          color=B.COLOR_PRIMARY),
        B.callback_button("📅 Неделя",
                          {"command": "rep_pick", "k": kind, "p": "week"},
                          color=B.COLOR_PRIMARY),
    )
    kb.row(
        B.callback_button("📅 Месяц",
                          {"command": "rep_pick", "k": kind, "p": "month"},
                          color=B.COLOR_PRIMARY),
        B.callback_button("📅 Период",
                          {"command": "rep_pick", "k": kind, "p": "custom"},
                          color=B.COLOR_SECONDARY),
    )
    kb.row(B.callback_button("📅 Всё время",
                             {"command": "rep_pick", "k": kind, "p": "all"},
                             color=B.COLOR_SECONDARY))
    return kb.dump()


def _period_range(choice: str) -> tuple[Optional[str], Optional[str]]:
    """Преобразовать выбор в (date_from, date_to). ISO 'YYYY-MM-DD'."""
    from datetime import datetime as _dt
    today = _dt.now().date()
    if choice == "today":
        return today.isoformat(), today.isoformat()
    if choice == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if choice == "month":
        return (today - timedelta(days=29)).isoformat(), today.isoformat()
    return None, None


def _parse_custom_period(raw: str) -> Optional[tuple[str, str]]:
    """Распарсить 'YYYY-MM-DD YYYY-MM-DD'."""
    from datetime import datetime as _dt
    parts = (raw or "").strip().split()
    if len(parts) != 2:
        return None
    try:
        d_from = _dt.strptime(parts[0], "%Y-%m-%d").date().isoformat()
        d_to   = _dt.strptime(parts[1], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    return d_from, d_to


# ─── Excel builders (ленивые импорты openpyxl) ──────────────────────

def _autosize_columns(ws) -> None:
    """Автоширина колонок в листе openpyxl."""
    for col in ws.columns:
        if not col or not col[0].value:
            continue
        length = max((len(str(c.value)) for c in col if c.value is not None),
                     default=10)
        ws.column_dimensions[col[0].column_letter].width = min(length + 2, 40)


def _build_admin_excel(filepath, date_from, date_to) -> bool:
    """
    Создать Excel-отчёт администратора.
    Возвращает True если файл создан, False если данных нет.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        logger.error("_build_admin_excel: openpyxl не установлен")
        return False

    try:
        orders = db.all_delivered_orders(date_from, date_to)
    except Exception:
        logger.exception("_build_admin_excel: ошибка БД (orders)")
        return False
    if not orders:
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Заказы"
    ws.append(["№ заказа", "Дата доставки", "Сумма ₽", "Оплата",
               "VK-ID клиента", "Доставщик"])
    for o in orders:
        ws.append([
            o["order_number"], str(o["delivered_at"]), o["total_price"],
            o["payment_method"] or "—", o["user_id"],
            o["courier_name"] or f"ID {o['courier_id']}",
        ])
    _autosize_columns(ws)

    ws2 = wb.create_sheet("Сводка")
    try:
        stats = db.admin_stats(date_from, date_to)
    except Exception:
        logger.exception("_build_admin_excel: admin_stats")
        wb.save(str(filepath))
        return True

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
    _autosize_columns(ws2)

    wb.save(str(filepath))
    return True


def _build_courier_excel(filepath, courier_id, date_from, date_to) -> bool:
    try:
        from openpyxl import Workbook
    except ImportError:
        return False
    try:
        orders = db.courier_orders(courier_id, date_from, date_to)
    except Exception:
        logger.exception("_build_courier_excel: ошибка БД")
        return False
    if not orders:
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Заказы"
    ws.append(["№ заказа", "Дата доставки", "Сумма ₽", "Оплата", "VK-ID клиента"])
    for o in orders:
        ws.append([
            o["order_number"], str(o["delivered_at"]), o["total_price"],
            o["payment_method"] or "—", o["user_id"],
        ])
    _autosize_columns(ws)

    ws2 = wb.create_sheet("Сводка")
    try:
        stats = db.courier_stats(courier_id, date_from, date_to)
    except Exception:
        wb.save(str(filepath))
        return True
    ws2.append(["Метрика", "Значение"])
    ws2.append(["Заказов",      stats["count"]])
    ws2.append(["Сумма ₽",       stats["total"]])
    ws2.append(["Переводом ₽",   stats["by_card"]])
    ws2.append(["Наличными ₽",   stats["by_cash"]])
    _autosize_columns(ws2)

    wb.save(str(filepath))
    return True


# ─── Кнопки точки входа в отчёты ────────────────────────────────────

@on_text(B.BTN_ADMIN_REPORT)
def admin_report_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    safe_send(peer_id, "📊 За какой период составить отчёт?",
              keyboard=_period_keyboard("adm"))


@on_text(B.BTN_COURIER_REPORT)
def courier_report_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_courier(user_id):
        return
    safe_send(peer_id, "📊 За какой период составить отчёт?",
              keyboard=_period_keyboard("cur"))


@on_callback("rep_pick")
def cb_report_pick(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")

    kind   = payload.get("k")   # "adm" / "cur"
    choice = payload.get("p")   # "today"/"week"/"month"/"custom"/"all"

    if kind == "adm" and not is_admin(user_id):
        return
    if kind == "cur" and not is_courier(user_id):
        return

    if choice == "custom":
        report_state[user_id] = {"kind": kind}
        text = ("Введите начало и конец периода через пробел в формате\n"
                "ГГГГ-ММ-ДД ГГГГ-ММ-ДД\n\n"
                "Пример: 2026-05-01 2026-05-11\n\n"
                "Отправьте «отмена», чтобы прервать.")
        if cmid is None or not edit_message(peer_id, cmid, text):
            safe_send(peer_id, text)
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    date_from, date_to = _period_range(choice)
    if cmid is not None:
        delete_message(peer_id, cmid)

    if kind == "adm":
        _send_admin_report(peer_id, date_from, date_to)
    else:
        _send_courier_report(peer_id, user_id, date_from, date_to)

    send_event_answer(event["event_id"], user_id, peer_id)


def _is_report_custom_input(user_id: int, _text: str) -> bool:
    return user_id in report_state


@on_state(_is_report_custom_input)
def report_custom_input(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = report_state.get(user_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        report_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    period = _parse_custom_period(text)
    if not period:
        safe_send(peer_id,
                  "⚠️ Неверный формат. Нужно: ГГГГ-ММ-ДД ГГГГ-ММ-ДД\n"
                  "Например: 2026-05-01 2026-05-11")
        return

    date_from, date_to = period
    kind = state.get("kind", "adm")
    report_state.pop(user_id, None)

    if kind == "adm":
        _send_admin_report(peer_id, date_from, date_to)
    else:
        _send_courier_report(peer_id, user_id, date_from, date_to)


# ─── Отправка отчётов ───────────────────────────────────────────────

def _send_admin_report(peer_id: int,
                       date_from: Optional[str],
                       date_to: Optional[str]) -> None:
    try:
        stats = db.admin_stats(date_from, date_to)
    except Exception:
        logger.exception("_send_admin_report: admin_stats")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    period_label = f"{date_from} — {date_to}" if date_from else "за всё время"
    t = stats["totals"]
    text = (
        f"📊 Отчёт по продажам ({period_label})\n\n"
        f"📦 Доставлено заказов: {t['count']}\n"
        f"💰 Общая выручка: {fmt_money(t['total'])} ₽\n"
        f"   💳 переводом: {fmt_money(t['by_card'])} ₽\n"
        f"   💵 наличными: {fmt_money(t['by_cash'])} ₽"
    )
    if stats.get("couriers"):
        text += "\n\nПо Доставщикам:\n"
        for c in stats["couriers"]:
            cname = c["courier_name"] or f"ID {c['courier_id']}"
            text += (f"• {cname}: {c['cnt']} зак., {fmt_money(c['total'])} ₽ "
                     f"(💳 {fmt_money(c['by_card'])} / 💵 {fmt_money(c['by_cash'])})\n")
    if len(text) > 3900:
        text = text[:3890] + "\n…(обрезано)"
    safe_send(peer_id, text)

    # Excel
    if t["count"] == 0:
        return
    from utils import temporary_file
    try:
        with temporary_file(prefix="admin_report_", suffix=".xlsx") as tmp:
            if _build_admin_excel(tmp, date_from, date_to):
                send_document(peer_id, str(tmp),
                              title="admin_report.xlsx",
                              text="📊 Подробный отчёт в Excel")
    except Exception:
        logger.exception("_send_admin_report: ошибка Excel")
        safe_send(peer_id, "⚠️ Не удалось создать Excel-отчёт.")


def _send_courier_report(peer_id: int, courier_id: int,
                         date_from: Optional[str],
                         date_to: Optional[str]) -> None:
    try:
        stats  = db.courier_stats(courier_id, date_from, date_to)
        rating = db.get_courier_rating(courier_id)
    except Exception:
        logger.exception("_send_courier_report: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    period_label = f"{date_from} — {date_to}" if date_from else "за всё время"
    text = (
        f"📊 Ваш отчёт ({period_label})\n\n"
        f"📦 Доставлено: {stats['count']}\n"
        f"💰 Сумма: {fmt_money(stats['total'])} ₽\n"
        f"   💳 переводом: {fmt_money(stats['by_card'])} ₽\n"
        f"   💵 наличными: {fmt_money(stats['by_cash'])} ₽\n\n"
        f"⭐ Ваш рейтинг: {fmt_rating(rating['avg'], rating['count'])}"
    )
    safe_send(peer_id, text)

    if stats["count"] == 0:
        return
    from utils import temporary_file
    try:
        with temporary_file(prefix=f"courier_{courier_id}_", suffix=".xlsx") as tmp:
            if _build_courier_excel(tmp, courier_id, date_from, date_to):
                send_document(peer_id, str(tmp),
                              title=f"courier_{courier_id}.xlsx",
                              text="📊 Подробный отчёт в Excel")
    except Exception:
        logger.exception("_send_courier_report: ошибка Excel")
        safe_send(peer_id, "⚠️ Не удалось создать Excel-отчёт.")


# ════════════════════════════════════════════════════════════════════
#   РЕДАКТОР ЦЕН
# ════════════════════════════════════════════════════════════════════

@on_text(B.BTN_EDIT_PRICES)
def admin_edit_prices_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    _admin_edit_prices_show(peer_id, page=0)


@on_callback("ep_page")
def cb_ep_page(event, payload):
    """Пагинация категорий в редакторе цен."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    _admin_edit_prices_show(peer_id, page=page,
                            conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


def _admin_edit_prices_show(peer_id: int, page: int = 0,
                            *, conversation_message_id: Optional[int] = None) -> None:
    kb_str = _build_categories_keyboard_for_admin(
        "pr_cat",
        extra_payload={"p": 0},
        label_prefix="💰 ",
        page_command="ep_page",
        page=page,
    )
    if kb_str is None:
        safe_send(peer_id, "Нет категорий.")
        return

    # Допишем «Закрыть»
    import json as _json
    kb_obj = _json.loads(kb_str)
    kb_obj["buttons"].append([{
        "action": {"type": "callback", "label": "⛔ Закрыть",
                   "payload": _json.dumps({"command": "pr_close"})},
        "color": B.COLOR_SECONDARY,
    }])
    kb_str = _json.dumps(kb_obj, ensure_ascii=False)

    text = "💰 Выберите категорию для редактирования цен:"
    if conversation_message_id is not None and edit_message(
            peer_id, conversation_message_id, text, keyboard=kb_str):
        return
    safe_send(peer_id, text, keyboard=kb_str)


@on_callback("pr_close")
def cb_pr_close(event, payload):
    cmid = event.get("conversation_message_id")
    if cmid is not None:
        delete_message(event["peer_id"], cmid)
    send_event_answer(event["event_id"], event["from_id"], event["peer_id"])


def _send_dishes_for_price_edit(peer_id: int, category_id: int, page: int,
                                *, conversation_message_id: Optional[int] = None) -> None:
    try:
        cat_name = db.get_category_name(category_id)
        with db.conn_ctx() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, price FROM menu "
                      "WHERE category_id = ? ORDER BY name", (category_id,))
            dishes = c.fetchall()
    except Exception:
        logger.exception("_send_dishes_for_price_edit: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    if not dishes:
        msg = f"В категории «{cat_name}» нет блюд."
        if conversation_message_id is not None:
            edit_message(peer_id, conversation_message_id, msg)
        else:
            safe_send(peer_id, msg)
        return

    total_pages = max(1, (len(dishes) + DISHES_PER_PAGE_ADMIN - 1) // DISHES_PER_PAGE_ADMIN)
    page = max(0, min(page, total_pages - 1))
    start = page * DISHES_PER_PAGE_ADMIN
    page_dishes = dishes[start:start + DISHES_PER_PAGE_ADMIN]

    kb = B.Keyboard(inline=True)
    for d in page_dishes:
        label = f"{d['name']} — {fmt_money(d['price'])} ₽"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": "pr_pick", "d": d["id"]},
            color=B.COLOR_PRIMARY,
        ))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(B.callback_button("◀",
                {"command": "pr_cat", "c": category_id, "p": page - 1}))
        nav.append(B.callback_button(f"{page + 1}/{total_pages}",
                                     {"command": "noop"},
                                     color=B.COLOR_SECONDARY))
        if page < total_pages - 1:
            nav.append(B.callback_button("▶",
                {"command": "pr_cat", "c": category_id, "p": page + 1}))
        kb.row(*nav)

    text = f"💰 {cat_name} — выберите блюдо:"
    if conversation_message_id is not None:
        if edit_message(peer_id, conversation_message_id, text, keyboard=kb.dump()):
            return
    safe_send(peer_id, text, keyboard=kb.dump())


@on_callback("pr_cat")
def cb_pr_cat(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        category_id = int(payload["c"])
        page        = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    _send_dishes_for_price_edit(peer_id, category_id, page,
                                conversation_message_id=cmid)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("pr_pick")
def cb_pr_pick(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        dish_id = int(payload["d"])
        dish = db.get_menu_item_by_id(dish_id)
    except Exception:
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not dish:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Блюдо не найдено"})
        return

    admin_edit_state[user_id] = {
        "dish_id":   dish_id,
        "name":      dish["name"],
        "old_price": dish["price"],
    }
    text = (f"💰 «{dish['name']}»\n"
            f"Текущая цена: {fmt_money(dish['price'])} ₽\n\n"
            f"Введите новую цену (целое или дробное).\n"
            f"Отправьте «отмена», чтобы прервать.")
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_admin_editing_price(user_id: int, _text: str) -> bool:
    return is_admin(user_id) and user_id in admin_edit_state


@on_state(_is_admin_editing_price)
def admin_save_new_price(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = admin_edit_state.get(user_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_edit_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    try:
        new_price = float(text.replace(",", ".").strip())
    except ValueError:
        safe_send(peer_id, "⚠️ Введите число. Например: 250 или 199.50")
        return
    if new_price <= 0:
        safe_send(peer_id, "⚠️ Цена должна быть больше 0.")
        return

    dish_id = state["dish_id"]
    name    = state["name"]
    old_price = state["old_price"]
    admin_edit_state.pop(user_id, None)

    try:
        db.update_dish_price(dish_id, new_price)
        db.log_user_action(user_id, f"updated_price:{dish_id}:{new_price}")
    except Exception:
        logger.exception("admin_save_new_price: ошибка БД")
        safe_send(peer_id, "⚠️ Не удалось сохранить.")
        return

    safe_send(peer_id,
              f"✅ Цена «{name}»: "
              f"{fmt_money(old_price)} → {fmt_money(new_price)} ₽")


# ════════════════════════════════════════════════════════════════════
#   БАЗА ПОЛЬЗОВАТЕЛЕЙ
# ════════════════════════════════════════════════════════════════════

def _build_users_page_keyboard(page: int = 0) -> tuple[str, Optional[str]]:
    """Вернуть (текст, JSON клавиатуры) для страницы списка пользователей."""
    try:
        users = db.get_all_users_for_admin()
    except Exception:
        logger.exception("_build_users_page_keyboard: ошибка БД")
        return "⚠️ Ошибка БД.", None

    total = len(users)
    if total == 0:
        return "👥 Пользователей нет.", None

    pages = max(1, (total + USERS_PER_PAGE_VK - 1) // USERS_PER_PAGE_VK)
    page = max(0, min(page, pages - 1))
    start = page * USERS_PER_PAGE_VK
    chunk = users[start:start + USERS_PER_PAGE_VK]

    kb = B.Keyboard(inline=True)
    for u in chunk:
        label_name = (u.get("name") or "(без имени)").strip() or "(без имени)"
        label = f"ID {u['id']} — {label_name}"
        if len(label) > B.MAX_LABEL_LEN:
            label = label[:B.MAX_LABEL_LEN - 1] + "…"
        kb.row(B.callback_button(
            label,
            {"command": "usr_view", "u": u["id"], "p": page},
            color=B.COLOR_PRIMARY,
        ))

    # Навигация
    nav = []
    if page > 0:
        nav.append(B.callback_button("« Назад",
            {"command": "usr_pg", "p": page - 1}))
    nav.append(B.callback_button(f"{page + 1}/{pages}",
                                 {"command": "noop"},
                                 color=B.COLOR_SECONDARY))
    if page < pages - 1:
        nav.append(B.callback_button("Вперёд »",
            {"command": "usr_pg", "p": page + 1}))
    kb.row(*nav)

    text = f"👥 База пользователей\nВсего: {total}. Страница {page + 1} из {pages}."
    return text, kb.dump()


@on_text(B.BTN_USERS_DB)
def admin_users_db(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    text, kb = _build_users_page_keyboard(page=0)
    safe_send(peer_id, text, keyboard=kb)


@on_callback("usr_pg")
def cb_usr_pg(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет доступа"})
        return
    try:
        page = int(payload.get("p", 0))
    except (ValueError, TypeError):
        page = 0
    text, kb = _build_users_page_keyboard(page=page)
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb):
        safe_send(peer_id, text, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("usr_view")
def cb_usr_view(event, payload):
    """Карточка одного пользователя для админа."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Нет доступа"})
        return
    try:
        uid  = int(payload["u"])
        page = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    try:
        u = db.get_user_for_admin(uid)
    except Exception:
        logger.exception("cb_usr_view: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if not u:
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Не найден"})
        return

    pii = {"name": u["name"], "phone": u["phone"], "address": u["address"]}
    text = format_user_card(uid, pii, for_self=False)

    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("✏️ Редактировать",
                          {"command": "usr_edit", "u": uid, "p": page},
                          color=B.COLOR_PRIMARY),
        B.callback_button("🗑 Удалить",
                          {"command": "usr_del", "u": uid, "p": page},
                          color=B.COLOR_NEGATIVE),
    )
    kb.row(B.callback_button("« К списку",
                             {"command": "usr_pg", "p": page},
                             color=B.COLOR_SECONDARY))
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("usr_edit")
def cb_usr_edit(event, payload):
    """Меню выбора поля для редактирования."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        uid  = int(payload["u"])
        page = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("👤 Имя",
                             {"command": "usr_efld", "u": uid, "f": "name", "p": page}))
    kb.row(B.callback_button("📞 Телефон",
                             {"command": "usr_efld", "u": uid, "f": "phone", "p": page}))
    kb.row(B.callback_button("🏠 Адрес",
                             {"command": "usr_efld", "u": uid, "f": "address", "p": page}))
    kb.row(B.callback_button("« Назад",
                             {"command": "usr_view", "u": uid, "p": page},
                             color=B.COLOR_SECONDARY))
    text = f"✏️ Что редактируем у пользователя {uid}?"
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("usr_efld")
def cb_usr_edit_field(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        uid   = int(payload["u"])
        field = payload["f"]
        page  = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if field not in ("name", "phone", "address"):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar", "text": "Неизвестное поле"})
        return

    admin_state[user_id] = {
        "action": "edit_user_field",
        "target": uid,
        "field":  field,
        "page":   page,
    }
    label = {"name": "новое ФИО",
             "phone": "новый телефон (10–15 цифр)",
             "address": "новый адрес"}[field]
    safe_send(peer_id,
              f"✏️ Введите {label} для пользователя {uid}.\n"
              f"Отправьте «отмена», чтобы прервать.")
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_admin_editing_user_field(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and isinstance(admin_state.get(user_id), dict)
            and admin_state[user_id].get("action") == "edit_user_field")


@on_state(_is_admin_editing_user_field)
def admin_edit_user_field_apply(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()
    state   = admin_state.get(user_id, {})

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return

    uid   = state["target"]
    field = state["field"]

    if not text:
        safe_send(peer_id, "⚠️ Пустое значение. Введите снова или «отмена».")
        return

    if field == "phone":
        normalized = normalize_phone(text)
        if normalized is None:
            safe_send(peer_id, "⚠️ Неверный формат. 10–15 цифр.")
            return
        text = normalized

    try:
        db.save_user_pii(uid, **{field: text})
        db.log_user_action(user_id, f"admin_edit_user:{uid}:{field}")
    except Exception:
        logger.exception("admin_edit_user_field_apply: ошибка БД")
        admin_state.pop(user_id, None)
        safe_send(peer_id, "⚠️ Не удалось сохранить.")
        return

    admin_state.pop(user_id, None)
    safe_send(peer_id, f"✅ Поле «{field}» пользователя {uid} обновлено.")


@on_callback("usr_del")
def cb_usr_del_ask(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        uid  = int(payload["u"])
        page = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    if is_admin(uid):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Нельзя удалить администратора"})
        return

    kb = B.Keyboard(inline=True)
    kb.row(
        B.callback_button("✅ Да, удалить",
                          {"command": "usr_del_do", "u": uid, "p": page},
                          color=B.COLOR_NEGATIVE),
        B.callback_button("⛔ Отмена",
                          {"command": "usr_view", "u": uid, "p": page},
                          color=B.COLOR_SECONDARY),
    )
    text = (f"⚠️ Удалить пользователя {uid}?\n\n"
            f"Будут стёрты ФИО, телефон, адрес, согласие и корзина.\n"
            f"Перед следующим заказом ему придётся снова заполнить профиль.")
    if cmid is None or not edit_message(peer_id, cmid, text, keyboard=kb.dump()):
        safe_send(peer_id, text, keyboard=kb.dump())
    send_event_answer(event["event_id"], user_id, peer_id)


@on_callback("usr_del_do")
def cb_usr_del_do(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return
    try:
        uid  = int(payload["u"])
        page = int(payload.get("p", 0))
    except (KeyError, ValueError, TypeError):
        send_event_answer(event["event_id"], user_id, peer_id)
        return
    if is_admin(uid):
        send_event_answer(event["event_id"], user_id, peer_id,
                          {"type": "show_snackbar",
                           "text": "Нельзя удалить администратора"})
        return

    try:
        rc = db.delete_user_completely(uid)
        db.log_user_action(user_id, f"admin_delete_user:{uid}")
    except Exception:
        logger.exception("cb_usr_del_do: ошибка БД")
        send_event_answer(event["event_id"], user_id, peer_id)
        return

    text, kb = _build_users_page_keyboard(page=page)
    note = "✅ Пользователь удалён.\n\n" if rc else "ℹ️ Записи уже не было.\n\n"
    full = note + text
    if cmid is None or not edit_message(peer_id, cmid, full, keyboard=kb):
        safe_send(peer_id, full, keyboard=kb)
    send_event_answer(event["event_id"], user_id, peer_id,
                      {"type": "show_snackbar", "text": "Удалено"})


# ════════════════════════════════════════════════════════════════════
#   ВСЕ ЗАКАЗЫ (АДМИН)
# ════════════════════════════════════════════════════════════════════

@on_text(B.BTN_ALL_ORDERS)
def admin_all_orders(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    try:
        orders = db.get_all_orders()
    except Exception:
        logger.exception("admin_all_orders: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return
    if not orders:
        safe_send(peer_id, "Заказов нет.")
        return

    # Разбиваем по чанкам ≤ 4000 символов
    header = "📋 Все заказы:\n\n"
    cur = header
    for o in orders:
        line = (f"{o['order_number']} · ID {o['user_id']} · "
                f"{fmt_money(o['total_price'])} ₽ · {o['status']}\n")
        if len(cur) + len(line) > 4000:
            safe_send(peer_id, cur)
            cur = ""
        cur += line
    if cur:
        safe_send(peer_id, cur)


# ════════════════════════════════════════════════════════════════════
#   РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ
# ════════════════════════════════════════════════════════════════════

@on_text(B.BTN_BROADCAST)
def admin_broadcast_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return
    admin_broadcast_state[user_id] = "awaiting"
    safe_send(peer_id,
              "✉ Введите текст рассылки (он уйдёт ВСЕМ пользователям).\n"
              "Отправьте «отмена», чтобы прервать.")


def _is_admin_broadcasting(user_id: int, _text: str) -> bool:
    return (is_admin(user_id)
            and admin_broadcast_state.get(user_id) == "awaiting")


@on_state(_is_admin_broadcasting)
def admin_broadcast_send(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip()

    if text.lower() in ("отмена", "cancel", "/cancel"):
        admin_broadcast_state.pop(user_id, None)
        safe_send(peer_id, "Отменено.")
        return
    if not text:
        safe_send(peer_id, "⚠️ Пустой текст. Введите или «отмена».")
        return

    admin_broadcast_state.pop(user_id, None)
    try:
        uids = db.get_all_user_ids()
    except Exception:
        logger.exception("admin_broadcast_send: ошибка БД")
        safe_send(peer_id, "⚠️ Ошибка БД.")
        return

    sent = 0
    failed = 0
    for uid in uids:
        if uid == user_id:   # самому себе не шлём
            continue
        if safe_send(uid, text) is not None:
            sent += 1
        else:
            failed += 1

    safe_send(peer_id,
              f"📢 Рассылка завершена.\n"
              f"✅ Доставлено: {sent}\n"
              f"❌ Не доставлено: {failed}")
    try:
        db.log_user_action(user_id, f"broadcast:{sent}/{sent+failed}")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#   ЭТАП 12: ЭКСПОРТ / ИМПОРТ МЕНЮ (JSON)
#
#   - "📤 Экспорт меню": db.export_menu_to_dict() → JSON → tmp-файл →
#     отправка как document. Формат — категории + блюда + photo + frozen.
#   - "📥 Импорт меню": admin сначала выбирает режим (очистить/дополнить),
#     потом присылает JSON-файл сообщением. Бот качает по url из
#     attachment.doc.url, парсит, передаёт в db.import_menu_from_dict().
#
#   Что отличается от Telegram:
#   - В Telegram файл — отдельное сообщение с content_type="document".
#     В VK — это attachment типа "doc" внутри обычного сообщения.
#   - Скачивание: в TG bot.get_file()+download_file(), в VK requests.get(url)
#     по прямой ссылке из doc.url. Никакого upload-сервера.
# ════════════════════════════════════════════════════════════════════

# Состояние ожидания файла импорта
# import_menu_state[user_id] = {"clear": bool}
import_menu_state: dict[int, dict] = {}


def _extract_vk_doc_url(attachments: list,
                        allowed_exts: tuple = ("json",)) -> Optional[tuple[str, str, str]]:
    """
    Из списка attachments выбрать первый документ с подходящим расширением.
    Возвращает (url, title, ext) или None.
    """
    if not attachments:
        return None
    for att in attachments:
        if not isinstance(att, dict) or att.get("type") != "doc":
            continue
        doc = att.get("doc") or {}
        ext = (doc.get("ext") or "").lower()
        url = doc.get("url")
        title = doc.get("title") or "file"
        if not url:
            continue
        if allowed_exts and ext not in allowed_exts:
            continue
        return url, title, ext
    return None


def _download_vk_doc(url: str, max_bytes: int = 5_000_000) -> Optional[bytes]:
    """
    Скачать содержимое документа VK. Ограничиваем размер 5 МБ.
    Для меню JSON это с большим запасом.
    """
    try:
        resp = requests.get(url, timeout=15, stream=True)
        resp.raise_for_status()
        data = b""
        for chunk in resp.iter_content(chunk_size=8192):
            data += chunk
            if len(data) > max_bytes:
                logger.warning(f"_download_vk_doc: файл больше {max_bytes} байт — обрезка")
                return None
        return data
    except Exception:
        logger.exception("_download_vk_doc: ошибка скачивания")
        return None


# ─── ЭКСПОРТ ─────────────────────────────────────────────────────────

@on_text(B.BTN_EXPORT_MENU)
def admin_export_menu(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return

    try:
        menu_data = db.export_menu_to_dict()
    except Exception:
        logger.exception("admin_export_menu: ошибка экспорта")
        safe_send(peer_id, "⚠️ Не удалось получить меню из БД.")
        return

    cat_count   = len(menu_data.get("categories", []))
    dish_count  = sum(len(c.get("dishes", [])) for c in menu_data.get("categories", []))

    if cat_count == 0 and dish_count == 0:
        safe_send(peer_id,
                  "📋 Меню пустое — нечего экспортировать.\n"
                  "Сначала добавьте категории и блюда.")
        return

    from datetime import datetime as _dt
    from utils import temporary_file

    try:
        with temporary_file(prefix="menu_export_", suffix=".json") as tmp_file:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(menu_data, f, ensure_ascii=False, indent=2)

            stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
            title = f"menu_export_{stamp}.json"
            caption = (
                f"📤 Экспорт меню\n"
                f"Категорий: {cat_count}\n"
                f"Блюд:      {dish_count}\n\n"
                f"Сохраните этот файл — потом можно восстановить через "
                f"«📥 Импорт меню»."
            )
            mid = send_document(peer_id, str(tmp_file), title=title, text=caption)
            if mid is None:
                safe_send(peer_id,
                          "⚠️ Не удалось отправить файл. "
                          "Попробуйте позже.")
                return

            try:
                db.log_user_action(user_id, "menu_exported")
            except Exception:
                pass
    except Exception:
        logger.exception("admin_export_menu: ошибка")
        safe_send(peer_id, "⚠️ Произошла ошибка при экспорте.")


# ─── ИМПОРТ ──────────────────────────────────────────────────────────

@on_text(B.BTN_IMPORT_MENU)
def admin_import_menu_start(event):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    if not is_admin(user_id):
        return

    kb = B.Keyboard(inline=True)
    kb.row(B.callback_button("✅ Да, очистить",
                             {"command": "imp_mode", "c": 1},
                             color=B.COLOR_NEGATIVE))
    kb.row(B.callback_button("➕ Нет, дополнить",
                             {"command": "imp_mode", "c": 0},
                             color=B.COLOR_POSITIVE))
    kb.row(B.callback_button("⛔ Отмена",
                             {"command": "imp_cancel"},
                             color=B.COLOR_SECONDARY))

    safe_send(peer_id,
              "📥 Импорт меню\n\n"
              "Очистить текущее меню перед импортом?\n\n"
              "• «Да, очистить» — удалит все существующие категории "
              "и блюда, а потом загрузит новые.\n"
              "• «Нет, дополнить» — добавит новые и обновит существующие. "
              "Старые не пострадают.\n\n"
              "После выбора пришлите JSON-файл с экспортом меню "
              "(прикрепите через скрепку 📎).",
              keyboard=kb.dump())


@on_callback("imp_cancel")
def cb_imp_cancel(event, payload):
    user_id = event["from_id"]
    cmid    = event.get("conversation_message_id")
    import_menu_state.pop(user_id, None)
    if cmid is None or not edit_message(event["peer_id"], cmid, "❌ Импорт отменён."):
        safe_send(event["peer_id"], "❌ Импорт отменён.")
    send_event_answer(event["event_id"], user_id, event["peer_id"])


@on_callback("imp_mode")
def cb_imp_mode(event, payload):
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    cmid    = event.get("conversation_message_id")
    if not is_admin(user_id):
        return

    try:
        clear = bool(int(payload.get("c", 0)))
    except (ValueError, TypeError):
        clear = False

    import_menu_state[user_id] = {"clear": clear}

    mode_str = "очистить и заменить" if clear else "дополнить существующее"
    text = (
        f"📥 Режим: {mode_str}\n\n"
        f"📎 Теперь прикрепите JSON-файл с экспортом меню "
        f"и отправьте сообщение.\n\n"
        f"Чтобы отменить — отправьте «отмена»."
    )
    if cmid is None or not edit_message(peer_id, cmid, text):
        safe_send(peer_id, text)
    send_event_answer(event["event_id"], user_id, peer_id)


def _is_admin_awaiting_import(user_id: int, _text: str) -> bool:
    return is_admin(user_id) and user_id in import_menu_state


@on_state(_is_admin_awaiting_import)
def admin_receive_import_file(event):
    """Принять документ с JSON-меню от админа."""
    user_id = event["from_id"]
    peer_id = event["peer_id"]
    text    = (event["text"] or "").strip().lower()
    state   = import_menu_state.get(user_id) or {}

    if text in ("отмена", "cancel", "/cancel"):
        import_menu_state.pop(user_id, None)
        safe_send(peer_id, "❌ Импорт отменён.")
        return

    # Ищем JSON-документ в attachments
    doc_info = _extract_vk_doc_url(event.get("attachments") or [],
                                   allowed_exts=("json",))
    if not doc_info:
        safe_send(peer_id,
                  "⚠️ В сообщении нет JSON-файла.\n"
                  "Прикрепите файл через скрепку 📎 (расширение .json) "
                  "или отправьте «отмена».")
        return

    url, title, _ext = doc_info
    raw = _download_vk_doc(url)
    if raw is None:
        import_menu_state.pop(user_id, None)
        safe_send(peer_id,
                  "⚠️ Не удалось скачать файл (или он слишком большой). "
                  "Попробуйте ещё раз.")
        return

    # Парсим JSON
    try:
        import_data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        import_menu_state.pop(user_id, None)
        safe_send(peer_id, f"⚠️ Не удалось распарсить JSON: {e}")
        return
    except UnicodeDecodeError:
        import_menu_state.pop(user_id, None)
        safe_send(peer_id,
                  "⚠️ Файл не в кодировке UTF-8. Сохраните его как UTF-8 "
                  "и попробуйте снова.")
        return

    if not isinstance(import_data, dict) or "categories" not in import_data:
        import_menu_state.pop(user_id, None)
        safe_send(peer_id,
                  "⚠️ Неверный формат: ожидается JSON-объект с ключом "
                  "«categories». Используйте файл из «📤 Экспорт меню».")
        return

    clear = state.get("clear", False)
    try:
        stats = db.import_menu_from_dict(import_data, clear)
    except Exception as e:
        logger.exception("admin_receive_import_file: import_menu_from_dict")
        import_menu_state.pop(user_id, None)
        safe_send(peer_id, f"⚠️ Ошибка импорта: {e}")
        return

    import_menu_state.pop(user_id, None)

    # Формируем отчёт
    lines = [
        "📊 Импорт меню завершён",
        "",
        "📁 Категории:",
        f"   • Создано: {stats.get('categories_created', 0)}",
        f"   • Обновлено: {stats.get('categories_updated', 0)}",
        "🍽️ Блюда:",
        f"   • Создано: {stats.get('dishes_created', 0)}",
        f"   • Обновлено: {stats.get('dishes_updated', 0)}",
    ]
    errors = stats.get("errors") or []
    if errors:
        lines.append("")
        lines.append("⚠️ Ошибки:")
        for e in errors[:5]:
            lines.append(f"   • {e}")
        if len(errors) > 5:
            lines.append(f"   • ... и ещё {len(errors) - 5} ошибок")

    safe_send(peer_id, "\n".join(lines))
    try:
        db.log_user_action(user_id,
                           f"menu_imported:created={stats.get('dishes_created', 0)}")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#   ОСНОВНОЙ ЦИКЛ — обработка событий LongPoll
# ════════════════════════════════════════════════════════════════════

def normalize_event(raw_event) -> Optional[dict]:
    """
    Привести событие message_new к удобному dict с полями:
      - from_id     (int)  — пользователь, написавший сообщение
      - peer_id     (int)  — куда отвечать (для ЛС == from_id, для бесед == 2e9 + chat_id)
      - text        (str)
      - payload     (dict | None) — payload нажатой кнопки
      - is_chat     (bool) — это беседа?
      - attachments (list)
      - raw         (исходный объект Message)
    """
    if raw_event.type != VkBotEventType.MESSAGE_NEW:
        return None

    msg = raw_event.object.message
    peer_id = msg["peer_id"]
    from_id = msg["from_id"]
    text    = (msg.get("text") or "").strip()
    is_chat = peer_id > 2_000_000_000

    # Если работа в беседах отключена — игнорируем
    if is_chat and not config.ENABLE_CHATS:
        return None

    # Игнорируем сообщения от других сообществ / самого себя
    if from_id < 0:
        return None

    # Парсим payload, если есть
    payload = None
    payload_raw = msg.get("payload")
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            payload = None

    return {
        "from_id":     from_id,
        "peer_id":     peer_id,
        "text":        text,
        "payload":     payload,
        "is_chat":     is_chat,
        "attachments": msg.get("attachments", []),
        "raw":         msg,
    }


def dispatch_message(event: dict) -> None:
    """Маршрутизация одного входящего сообщения по хэндлерам."""
    user_id = event["from_id"]
    text    = event["text"]
    payload = event["payload"]

    # 1) payload имеет наивысший приоритет (нажатие кнопки с command)
    if payload and isinstance(payload, dict):
        cmd = payload.get("command") or payload.get("cmd")
        if cmd and cmd in PAYLOAD_HANDLERS:
            try:
                PAYLOAD_HANDLERS[cmd](event, payload)
                return
            except Exception:
                logger.exception(f"Ошибка в payload-хэндлере '{cmd}'")
                safe_send(event["peer_id"], "Произошла ошибка. Попробуйте ещё раз.")
                return

    # 2) Состояния (например, идёт ввод имени, цены, скидки и т.д.)
    for predicate, handler in STATE_HANDLERS:
        try:
            if predicate(user_id, text):
                handler(event)
                return
        except Exception:
            logger.exception("Ошибка в state-предикате")
            continue

    # 3) Точное совпадение текста с кнопкой
    if text in TEXT_HANDLERS:
        try:
            TEXT_HANDLERS[text](event)
            return
        except Exception:
            logger.exception(f"Ошибка в text-хэндлере '{text}'")
            safe_send(event["peer_id"], "Произошла ошибка. Попробуйте ещё раз.")
            return

    # 4) Команды /start, /help и т.п.
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        if cmd in TEXT_HANDLERS:
            TEXT_HANDLERS[cmd](event)
            return

    # 5) Ничего не подошло — для ЛС показываем главное меню, для беседы молчим
    if not event["is_chat"]:
        # Можно отвечать "не понял" или просто показывать меню. Выберем мягкий
        # вариант — показываем меню только при первой коммуникации, иначе тихо.
        # Для каркаса оставим показ меню.
        send_main_menu(event["peer_id"], user_id)


def dispatch_callback(raw_event) -> None:
    """Обработка нажатий callback-кнопок (event_type == message_event)."""
    obj = raw_event.object
    user_id = obj["user_id"]
    peer_id = obj["peer_id"]
    event_id = obj["event_id"]
    payload = obj.get("payload") or {}

    if not isinstance(payload, dict):
        send_event_answer(event_id, user_id, peer_id)
        return

    cmd = payload.get("command") or payload.get("cmd")
    if cmd and cmd in CALLBACK_HANDLERS:
        try:
            # Конструируем "event-like" объект для единообразия с message-хэндлерами
            cb_event = {
                "from_id": user_id,
                "peer_id": peer_id,
                "text":    "",
                "payload": payload,
                "is_chat": peer_id > 2_000_000_000,
                "attachments": [],
                "raw":     obj,
                "event_id": event_id,
                "conversation_message_id": obj.get("conversation_message_id"),
            }
            CALLBACK_HANDLERS[cmd](cb_event, payload)
        except Exception:
            logger.exception(f"Ошибка в callback-хэндлере '{cmd}'")
            send_event_answer(event_id, user_id, peer_id,
                              {"type": "show_snackbar", "text": "Ошибка, попробуйте ещё раз"})
    else:
        # Неизвестная команда — просто молча гасим "часики" на кнопке
        send_event_answer(event_id, user_id, peer_id)


def main() -> None:
    """Точка входа. Запускает Long Poll и крутится вечно."""
    db.init_schema()
    logger.info(f"VK-бот запущен. group_id={config.VK_GROUP_ID}, "
                f"admin_vk_id={config.ADMIN_VK_ID}, chats={'on' if config.ENABLE_CHATS else 'off'}")

    while True:
        try:
            for raw_event in longpoll.listen():
                if raw_event.type == VkBotEventType.MESSAGE_NEW:
                    msg = normalize_event(raw_event)
                    if msg is None:
                        continue
                    dispatch_message(msg)
                elif raw_event.type == VkBotEventType.MESSAGE_EVENT:
                    dispatch_callback(raw_event)
                # Остальные типы (message_reply, group_join, etc.) игнорируем
        except KeyboardInterrupt:
            logger.info("Остановка по Ctrl+C")
            return
        except Exception:
            logger.exception("Сбой в основном цикле, перезапуск через 3 сек.")
            time.sleep(3)


if __name__ == "__main__":
    main()