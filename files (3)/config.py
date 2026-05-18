"""
config.py
=========
Централизованная загрузка конфигурации из переменных окружения для VK-бота.
Структурно почти идентичен Telegram-версии. Поменялись только ключи:
BOT_TOKEN → VK_TOKEN, ADMIN_CHAT_ID → ADMIN_VK_ID, добавился VK_GROUP_ID.

Принцип тот же: если обязательная переменная не задана — падаем сразу
при импорте, а не где-то в середине работы.
"""

import os
from pathlib import Path

# Опционально подгружаем .env. Если python-dotenv не стоит — пропускаем.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _require(name: str) -> str:
    """Прочитать обязательную переменную или упасть с понятной ошибкой."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Переменная окружения {name} не задана. "
            f"Скопируйте .env.example в .env и заполните."
        )
    return value


# --- Обязательные ---
VK_TOKEN: str = _require("VK_TOKEN")
VK_GROUP_ID: int = int(_require("VK_GROUP_ID"))
ADMIN_VK_ID: int = int(_require("ADMIN_VK_ID"))

# FERNET_KEY читается лениво в crypto_utils, но проверим наличие здесь.
_require("FERNET_KEY")

# --- С разумными дефолтами ---
DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")
ADMIN_VK_SCREEN: str = os.getenv("ADMIN_VK_SCREEN", "")  # для кнопки "Связаться"
CONSENT_VERSION: str = os.getenv("CONSENT_VERSION", "1.0")
PRIVACY_POLICY_URL: str = os.getenv(
    "PRIVACY_POLICY_URL",
    "https://telegra.ph/Politika-konfidencialnosti",
)
ENABLE_CHATS: bool = os.getenv("ENABLE_CHATS", "1") == "1"

# Гарантируем, что папка для БД существует.
_db_dir = Path(DB_PATH).parent
if _db_dir and not _db_dir.exists():
    _db_dir.mkdir(parents=True, exist_ok=True)
