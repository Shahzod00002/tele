"""
config.py
=========
Централизованная загрузка конфигурации из переменных окружения.
Поддерживает .env через python-dotenv (если установлен), иначе работает
напрямую с os.environ.

Принцип: если обязательная переменная не задана — падаем сразу при импорте,
а не где-то на 100-й строке логики во время работы.
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
BOT_TOKEN: str = _require("BOT_TOKEN")
ADMIN_CHAT_ID: int = int(_require("ADMIN_CHAT_ID"))
# FERNET_KEY читается лениво в crypto_utils, но проверим наличие здесь.
_require("FERNET_KEY")

# --- С разумными дефолтами ---
DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")
SUPPORT_WEBAPP_URL: str = os.getenv("SUPPORT_WEBAPP_URL", "")
CONSENT_VERSION: str = os.getenv("CONSENT_VERSION", "1.0")
PRIVACY_POLICY_URL: str = os.getenv(
    "PRIVACY_POLICY_URL",
    "https://telegra.ph/Politika-konfidencialnosti",
)

# Гарантируем, что папка для БД существует.
_db_dir = Path(DB_PATH).parent
if _db_dir and not _db_dir.exists():
    _db_dir.mkdir(parents=True, exist_ok=True)

# Добавьте в конец файла config.py:
