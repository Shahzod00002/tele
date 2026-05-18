"""
crypto_utils.py
================
Утилита для шифрования персональных данных (ФИО, телефон, адрес) перед
записью в БД. Соответствует требованиям ФЗ-152 в части «принятия правовых,
организационных и технических мер по защите ПДн».

Реализация: симметричное шифрование Fernet (AES-128-CBC + HMAC-SHA256)
из пакета `cryptography`. Ключ — 32 байта в urlsafe-base64, читается ТОЛЬКО
из переменной окружения FERNET_KEY. В коде ключ не хранится никогда.

Хранение шифротекста: Fernet возвращает urlsafe-base64-строку, её удобно
класть в TEXT-колонку. Если предпочитаете BLOB — токен можно сохранять
и как bytes без декодирования.

Использование:
    from crypto_utils import encrypt, decrypt, encrypt_optional, decrypt_optional

    enc_phone = encrypt("+79991234567")        # str (base64)
    phone     = decrypt(enc_phone)             # "+79991234567"

    # Если значение может быть None:
    enc = encrypt_optional(maybe_none_value)   # вернёт None при None на входе
    val = decrypt_optional(enc)
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_FERNET: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Ленивая инициализация Fernet. При первом вызове читаем ключ из env."""
    global _FERNET
    if _FERNET is not None:
        return _FERNET

    key = os.getenv("FERNET_KEY")
    if not key:
        raise RuntimeError(
            "FERNET_KEY не задан в переменных окружения. "
            "Сгенерируйте: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )

    # Fernet принимает и str, и bytes — нормализуем.
    if isinstance(key, str):
        key = key.encode("ascii")

    try:
        _FERNET = Fernet(key)
    except (ValueError, TypeError) as e:
        raise RuntimeError(
            "Неверный формат FERNET_KEY. Ожидается 32 байта в urlsafe-base64."
        ) from e

    return _FERNET


def encrypt(plaintext: str) -> str:
    """
    Зашифровать строку. Возвращает urlsafe-base64-токен (str), безопасный
    для хранения в TEXT-колонке SQLite.
    """
    if not isinstance(plaintext, str):
        raise TypeError(f"encrypt() принимает str, получено {type(plaintext).__name__}")
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(ciphertext: str) -> str:
    """
    Расшифровать токен, полученный из encrypt(). Возвращает исходную строку.
    Бросает cryptography.fernet.InvalidToken, если ключ не подходит или
    данные повреждены.
    """
    if not isinstance(ciphertext, str):
        raise TypeError(
            f"decrypt() принимает str, получено {type(ciphertext).__name__}"
        )
    try:
        plain = _get_fernet().decrypt(ciphertext.encode("ascii"))
    except InvalidToken:
        logger.error("Не удалось расшифровать ПДн: неверный ключ или повреждённые данные")
        raise
    return plain.decode("utf-8")


def encrypt_optional(plaintext: Optional[str]) -> Optional[str]:
    """То же, что encrypt(), но прозрачно пропускает None и пустые строки."""
    if plaintext is None or plaintext == "":
        return None
    return encrypt(plaintext)


def decrypt_optional(ciphertext: Optional[str]) -> Optional[str]:
    """
    Расшифровать, но мягко обрабатывать None и старые незашифрованные
    значения (на случай частично выполненной миграции — логируем варнинг).
    """
    if ciphertext is None or ciphertext == "":
        return None
    try:
        return decrypt(ciphertext)
    except InvalidToken:
        # Возможно, в БД остались данные в открытом виде (миграция не доехала).
        # Возвращаем как есть, чтобы бот не падал, но кричим в лог.
        logger.warning(
            "decrypt_optional: значение не расшифровывается — "
            "вероятно, осталось незашифрованным. Запустите migrations/encrypt_existing.py"
        )
        return ciphertext


# --- Утилита для CLI: быстрая генерация нового ключа ---
if __name__ == "__main__":
    print(Fernet.generate_key().decode())