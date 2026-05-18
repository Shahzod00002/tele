"""
utils.py
========
Вспомогательные утилиты для работы с временными файлами, форматированием и т.д.
"""

import os
import uuid
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Union, BinaryIO
from datetime import datetime

logger = logging.getLogger(__name__)


@contextmanager
def temporary_file(
        prefix: str = "tmp_",
        suffix: str = "",
        directory: str = "tmp",
        delete_on_exit: bool = True,
        auto_cleanup_old: bool = True,
        max_age_minutes: int = 60
):
    """
    Контекстный менеджер для безопасной работы с временными файлами.

    Args:
        prefix: Префикс имени файла
        suffix: Суффикс (включая расширение, например ".txt")
        directory: Директория для временных файлов
        delete_on_exit: Удалять файл при выходе из контекста
        auto_cleanup_old: Очищать старые файлы при создании нового
        max_age_minutes: Максимальный возраст файла для автоочистки

    Yields:
        Path: Путь к временному файлу

    Example:
        with temporary_file(suffix=".xlsx") as tmp_file:
            wb.save(tmp_file)
            with open(tmp_file, "rb") as f:
                bot.send_document(chat_id, f)
        # Файл автоматически удалён
    """
    # Создаём директорию если её нет
    tmp_dir = Path(directory)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Автоматическая очистка старых файлов
    if auto_cleanup_old:
        _cleanup_old_files(tmp_dir, max_age_minutes)

    # Генерируем уникальное имя
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = tmp_dir / f"{prefix}{timestamp}_{unique_id}{suffix}"

    try:
        yield filename
    finally:
        if delete_on_exit and filename.exists():
            try:
                filename.unlink()
                logger.debug(f"Удалён временный файл: {filename}")
            except Exception as e:
                logger.error(f"Ошибка удаления {filename}: {e}")


@contextmanager
def temporary_directory(
        prefix: str = "tmp_dir_",
        directory: str = "tmp",
        delete_on_exit: bool = True
):
    """
    Контекстный менеджер для временной директории.

    Args:
        prefix: Префикс имени директории
        directory: Родительская директория
        delete_on_exit: Удалять директорию при выходе

    Yields:
        Path: Путь к временной директории
    """
    tmp_dir = Path(directory)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    unique_id = uuid.uuid4().hex[:8]
    dir_path = tmp_dir / f"{prefix}{unique_id}"
    dir_path.mkdir()

    try:
        yield dir_path
    finally:
        if delete_on_exit and dir_path.exists():
            try:
                import shutil
                shutil.rmtree(dir_path)
                logger.debug(f"Удалена временная директория: {dir_path}")
            except Exception as e:
                logger.error(f"Ошибка удаления директории {dir_path}: {e}")


def _cleanup_old_files(directory: Path, max_age_minutes: int):
    """
    Удаляет файлы старше указанного возраста.
    """
    if not directory.exists():
        return

    now = datetime.now()
    for file_path in directory.iterdir():
        if file_path.is_file():
            try:
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                age = now - file_mtime

                if age.total_seconds() > max_age_minutes * 60:
                    file_path.unlink()
                    logger.info(f"Автоочистка: удалён {file_path.name} (возраст: {age.total_seconds() / 60:.1f} мин)")
            except Exception as e:
                logger.error(f"Ошибка автоочистки {file_path.name}: {e}")


def cleanup_all_temp_files(directory: str = "tmp", max_age_minutes: int = 0):
    """
    Принудительная очистка всех временных файлов.

    Args:
        directory: Директория для очистки
        max_age_minutes: Удалять только файлы старше N минут (0 = все)
    """
    tmp_dir = Path(directory)
    if not tmp_dir.exists():
        return

    deleted_count = 0
    deleted_size = 0

    for file_path in tmp_dir.iterdir():
        if file_path.is_file():
            should_delete = True

            if max_age_minutes > 0:
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                age = datetime.now() - file_mtime
                should_delete = age.total_seconds() > max_age_minutes * 60

            if should_delete:
                size = file_path.stat().st_size
                try:
                    file_path.unlink()
                    deleted_count += 1
                    deleted_size += size
                except Exception as e:
                    logger.error(f"Ошибка удаления {file_path.name}: {e}")

    # Удаляем пустые директории
    for subdir in tmp_dir.iterdir():
        if subdir.is_dir() and not any(subdir.iterdir()):
            try:
                subdir.rmdir()
                logger.info(f"Удалена пустая директория: {subdir}")
            except Exception as e:
                logger.error(f"Ошибка удаления директории {subdir}: {e}")

    if deleted_count > 0:
        logger.info(f"Очистка завершена: удалено {deleted_count} файлов, {deleted_size / 1024:.2f} KB")

    return deleted_count, deleted_size