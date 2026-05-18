"""
load_test.py
============
Нагрузочное тестирование бота с имитацией 1000 пользователей

Особенности:
- Многопоточная симуляция пользователей
- Измерение времени ответа
- Статистика по операциям
- Отчёт о производительности
"""

import os
import sys
import time
import json
import random
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import defaultdict
import statistics

# Добавляем корневую директорию
sys.path.insert(0, os.path.dirname(__file__))

# Настройка тестового окружения
os.environ["BOT_TOKEN"] = "test_token_load_test"
os.environ["ADMIN_CHAT_ID"] = "999999999"

import crypto_utils
os.environ["FERNET_KEY"] = crypto_utils.Fernet.generate_key().decode()

# Используем отдельную БД для нагрузочного тестирования
TEST_DB_PATH = "load_test_bot.db"
os.environ["DB_PATH"] = TEST_DB_PATH

import db
import config

# Отключаем логирование для производительности
import logging
logging.basicConfig(level=logging.WARNING)


@dataclass
class TestMetrics:
    """Метрики производительности"""
    operation: str
    success_count: int = 0
    error_count: int = 0
    total_time: float = 0.0
    times: List[float] = None

    def __post_init__(self):
        self.times = []

    def add_success(self, duration: float):
        self.success_count += 1
        self.total_time += duration
        self.times.append(duration)

    def add_error(self):
        self.error_count += 1

    @property
    def avg_time(self) -> float:
        if self.success_count == 0:
            return 0.0
        return self.total_time / self.success_count

    @property
    def min_time(self) -> float:
        if not self.times:
            return 0.0
        return min(self.times)

    @property
    def max_time(self) -> float:
        if not self.times:
            return 0.0
        return max(self.times)

    @property
    def p95_time(self) -> float:
        if not self.times:
            return 0.0
        sorted_times = sorted(self.times)
        index = int(len(sorted_times) * 0.95)
        return sorted_times[min(index, len(sorted_times) - 1)]


class LoadTester:
    """Нагрузочный тестер"""

    def __init__(self, num_users: int = 1000, users_per_second: int = 50):
        self.num_users = num_users
        self.users_per_second = users_per_second
        self.metrics: Dict[str, TestMetrics] = defaultdict(lambda: TestMetrics("unknown"))
        self.lock = threading.Lock()
        self.active_users = 0
        self.completed_users = 0
        self.start_time = None
        self.end_time = None

        # Данные пользователей
        self.user_ids = []
        self.courier_ids = []

        # Тестовые данные
        self.test_names = [
            "Иван Петров", "Мария Сидорова", "Алексей Иванов", "Елена Козлова",
            "Дмитрий Соколов", "Ольга Новикова", "Сергей Зайцев", "Анна Морозова",
            "Владимир Волков", "Татьяна Соловьева", "Андрей Васильев", "Наталья Павлова",
            "Павел Степанов", "Екатерина Николаева", "Михаил Федоров"
        ]

        self.test_phones = [
            "+79161234567", "+79162345678", "+79163456789", "+79164567890",
            "+79165678901", "+79166789012", "+79167890123", "+79168901234"
        ]

        self.test_addresses = [
            "ул. Ленина, д.1", "пр. Мира, д.10", "ул. Гагарина, д.5", "ул. Пушкина, д.15",
            "пр. Вернадского, д.20", "ул. Тверская, д.7", "ул. Арбат, д.25", "ул. Новый Арбат, д.3"
        ]

        self.test_dishes = [
            "Пицца Маргарита", "Пицца Пепперони", "Салат Цезарь", "Салат Греческий",
            "Бургер Классический", "Бургер Двойной", "Суп Томатный", "Суп Грибной"
        ]

    def setup_test_data(self):
        """Подготовка тестовых данных"""
        print("📦 Подготовка тестовых данных...")

        # Очищаем старую БД
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

        # Инициализируем схему
        db.init_schema()

        # Добавляем тестовые категории и блюда
        cat_id = db.add_category("Тестовая категория")
        for dish in self.test_dishes:
            db.add_menu_item(dish, random.uniform(100, 500), cat_id)

        # Добавляем курьеров
        for i in range(10):  # 10 курьеров для 1000 пользователей
            courier_id = 200000 + i
            db.add_courier(f"Курьер {i+1}", courier_id, f"+7999{i:04}1111")
            self.courier_ids.append(courier_id)

        print(f"✓ Создано {len(self.test_dishes)} блюд")
        print(f"✓ Создано {len(self.courier_ids)} курьеров")

    def simulate_user(self, user_id: int, user_data: Dict):
        """Симуляция действий одного пользователя"""

        def measure(operation: str, func, *args, **kwargs):
            """Измерить время выполнения операции"""
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = (time.perf_counter() - start) * 1000  # в миллисекундах
                with self.lock:
                    self.metrics[operation].add_success(duration)
                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                with self.lock:
                    self.metrics[operation].add_error()
                print(f"Ошибка у user {user_id} в {operation}: {e}")
                return None

        try:
            # 1. Регистрация и согласие
            measure("register_user", db.save_user_pii,
                   user_id,
                   name=user_data["name"],
                   phone=user_data["phone"],
                   address=user_data["address"])

            measure("record_consent", db.record_consent,
                   user_id, "1.0", "accepted")

            # 2. Выбор курьера
            courier_id = random.choice(self.courier_ids)
            measure("select_courier", db.set_user_preferred_courier,
                   user_id, courier_id)

            # 3. Добавление товаров в корзину (2-5 товаров)
            cart_total = 0
            num_items = random.randint(2, 5)

            for i in range(num_items):
                dish = random.choice(self.test_dishes)
                price = random.uniform(100, 500)
                quantity = random.randint(1, 3)

                measure("add_to_cart", db.add_to_cart,
                       user_id, f"{dish} {i}", price, quantity)
                cart_total += price * quantity

            # 4. Проверка корзины
            cart = measure("get_cart", db.get_cart, user_id)
            if cart:
                total = measure("get_cart_total", db.get_cart_total, user_id)

            # 5. Создание заказа (50% пользователей)
            if random.random() < 0.5:
                order_number = f"LOAD_{user_id}_{int(time.time() * 1000)}"
                payment_method = random.choice(["Перевод 💳", "Наличными 💵"])
                comment = random.choice(["", "Острый", "Без лука", "Побыстрее", "Колокольчик у двери"])

                measure("create_order", db.create_order,
                       user_id, order_number, cart_total, payment_method, courier_id, comment)

                # 6. Обновление статуса (если заказ создан)
                if random.random() < 0.3:
                    measure("update_order_status", db.update_order_status,
                           order_number, "Принято")

                if random.random() < 0.2:
                    measure("update_order_status", db.update_order_status,
                           order_number, "Доставлено")

                # 7. Оценка курьера (если доставлено)
                if random.random() < 0.1:
                    stars = random.randint(1, 5)
                    measure("rate_courier", db.save_rating,
                           order_number, courier_id, user_id, stars)

            # 8. Очистка корзины (30% пользователей)
            if random.random() < 0.3:
                measure("clear_cart", db.clear_cart, user_id)

            # 9. Получение истории заказов
            measure("get_user_orders", db.get_user_orders, user_id, 10)

            # 10. Добавление в лог действий
            measure("log_action", db.log_user_action, user_id, "load_test_action")

            with self.lock:
                self.completed_users += 1
                if self.completed_users % 100 == 0:
                    print(f"Прогресс: {self.completed_users}/{self.num_users} пользователей завершили тест")

        except Exception as e:
            print(f"Критическая ошибка у пользователя {user_id}: {e}")
            with self.lock:
                self.metrics["critical_error"].add_error()

    def run_load_test(self):
        """Запуск нагрузочного теста"""
        print(f"\n🚀 Запуск нагрузочного теста с {self.num_users} пользователями")
        print(f"📊 Скорость: {self.users_per_second} пользователей/сек")
        print("=" * 60)

        # Подготовка данных пользователей
        user_data_list = []
        for i in range(self.num_users):
            user_id = 100000 + i
            user_data = {
                "name": random.choice(self.test_names) + f" {i}",
                "phone": f"+7999{i:06d}",
                "address": random.choice(self.test_addresses) + f", кв.{i%100}"
            }
            user_data_list.append((user_id, user_data))
            self.user_ids.append(user_id)

        self.start_time = time.time()

        # Запуск пользователей с заданной скоростью
        threads = []
        users_started = 0

        for user_id, user_data in user_data_list:
            # Ожидание для соблюдения скорости
            if users_started > 0 and users_started % self.users_per_second == 0:
                time.sleep(1)

            thread = threading.Thread(
                target=self.simulate_user,
                args=(user_id, user_data),
                daemon=True
            )
            thread.start()
            threads.append(thread)
            users_started += 1

            if users_started % 100 == 0:
                print(f"Запущено: {users_started}/{self.num_users} пользователей")

        # Ожидание завершения всех потоков
        for thread in threads:
            thread.join(timeout=30)

        self.end_time = time.time()

        # Генерация отчёта
        self.generate_report()

    def generate_report(self):
        """Генерация отчёта о нагрузочном тестировании"""
        total_time = self.end_time - self.start_time
        successful_users = self.completed_users

        print("\n" + "=" * 60)
        print("📊 ОТЧЁТ О НАГРУЗОЧНОМ ТЕСТИРОВАНИИ")
        print("=" * 60)
        print(f"\n📈 Общая статистика:")
        print(f"   • Пользователей: {self.num_users}")
        print(f"   • Успешно завершили: {successful_users}")
        print(f"   • Неудачно: {self.num_users - successful_users}")
        print(f"   • Общее время: {total_time:.2f} секунд")
        print(f"   • Средняя скорость: {self.num_users / total_time:.2f} пользователей/сек")

        print(f"\n⚡ Производительность операций:")
        print(f"{'Операция':<25} {'Успешно':<10} {'Ошибки':<10} {'Среднее(мс)':<12} {'Min(мс)':<10} {'Max(мс)':<10} {'P95(мс)':<10}")
        print("-" * 90)

        for op_name, metrics in sorted(self.metrics.items()):
            if metrics.success_count > 0:
                print(f"{op_name:<25} {metrics.success_count:<10} {metrics.error_count:<10} "
                      f"{metrics.avg_time:<12.2f} {metrics.min_time:<10.2f} "
                      f"{metrics.max_time:<10.2f} {metrics.p95_time:<10.2f}")

        # Анализ узких мест
        print(f"\n🐌 Самые медленные операции (по среднему времени):")
        slowest = sorted(
            [(name, m.avg_time) for name, m in self.metrics.items() if m.success_count > 0],
            key=lambda x: x[1],
            reverse=True
        )[:5]

        for name, avg_time in slowest:
            print(f"   • {name}: {avg_time:.2f} мс")

        # Оценка качества
        print(f"\n🎯 Оценка качества:")

        error_rate = (self.num_users - successful_users) / self.num_users * 100
        if error_rate < 1:
            print(f"   ✅ Отлично! Уровень ошибок: {error_rate:.2f}%")
        elif error_rate < 5:
            print(f"   ⚠️ Хорошо, но есть проблемы. Уровень ошибок: {error_rate:.2f}%")
        else:
            print(f"   ❌ Требуется оптимизация. Уровень ошибок: {error_rate:.2f}%")

        # Рекомендации
        print(f"\n💡 Рекомендации:")

        slow_db_ops = [(name, m.avg_time) for name, m in self.metrics.items()
                      if m.avg_time > 100 and m.success_count > 0]
        if slow_db_ops:
            print(f"   • Оптимизировать медленные операции БД:")
            for name, avg_time in slow_db_ops[:3]:
                print(f"     - {name} ({avg_time:.0f} мс)")

        if self.num_users / total_time < 20:
            print(f"   • Увеличить скорость обработки запросов (текущая: {self.num_users / total_time:.1f} п/с)")

        print("\n" + "=" * 60)

    def cleanup(self):
        """Очистка после теста"""
        if os.path.exists(TEST_DB_PATH):
            # Сохраняем копию для анализа
            backup_name = f"load_test_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            os.rename(TEST_DB_PATH, backup_name)
            print(f"\n📁 Результаты сохранены в: {backup_name}")


class ConcurrentLoadTester:
    """Тест с разной нагрузкой"""

    def __init__(self):
        self.results = []

    def test_scenarios(self):
        """Запуск различных сценариев нагрузки"""

        scenarios = [
            {"users": 100, "rate": 10, "name": "Лёгкая нагрузка"},
            {"users": 500, "rate": 25, "name": "Средняя нагрузка"},
            {"users": 1000, "rate": 50, "name": "Высокая нагрузка"},
            {"users": 2000, "rate": 100, "name": "Экстремальная нагрузка (если хватит ресурсов)"},
        ]

        print("\n🔥 ЗАПУСК СЦЕНАРИЕВ НАГРУЗКИ\n")

        for scenario in scenarios:
            print(f"\n{'='*60}")
            print(f"Сценарий: {scenario['name']}")
            print(f"Пользователей: {scenario['users']}")
            print(f"Скорость: {scenario['rate']} п/сек")
            print(f"{'='*60}")

            tester = LoadTester(
                num_users=scenario["users"],
                users_per_second=scenario["rate"]
            )

            try:
                tester.setup_test_data()
                tester.run_load_test()

                self.results.append({
                    "scenario": scenario["name"],
                    "users": scenario["users"],
                    "rate": scenario["rate"],
                    "success_rate": tester.completed_users / scenario["users"] * 100,
                    "total_time": tester.end_time - tester.start_time if tester.end_time else 0
                })

                tester.cleanup()

            except Exception as e:
                print(f"❌ Ошибка в сценарии {scenario['name']}: {e}")
                continue

            # Пауза между сценариями
            if scenario != scenarios[-1]:
                print("\n⏸ Пауза 5 секунд перед следующим сценарием...")
                time.sleep(5)

        # Итоговый отчёт
        self.print_summary()

    def print_summary(self):
        """Итоговый отчёт по всем сценариям"""
        print("\n\n" + "=" * 80)
        print("📊 ИТОГОВЫЙ ОТЧЁТ ПО ВСЕМ СЦЕНАРИЯМ")
        print("=" * 80)

        print(f"\n{'Сценарий':<25} {'Пользователей':<12} {'Скорость':<10} {'Успех(%)':<10} {'Время(с)':<10}")
        print("-" * 80)

        for result in self.results:
            print(f"{result['scenario']:<25} {result['users']:<12} {result['rate']:<10} "
                  f"{result['success_rate']:<10.1f} {result['total_time']:<10.1f}")

        # Вывод рекомендаций по масштабированию
        print(f"\n🚀 Рекомендации по масштабированию:")

        max_successful = max([r for r in self.results if r["success_rate"] > 95],
                            key=lambda x: x["users"], default=None)

        if max_successful:
            print(f"   • Максимальная стабильная нагрузка: {max_successful['users']} пользователей")
            print(f"   • При скорости: {max_successful['rate']} пользователей/сек")

        print(f"\n💡 Для увеличения производительности:")
        print(f"   • Использовать пул соединений с БД")
        print(f"   • Внедрить кэширование (Redis)")
        print(f"   • Оптимизировать индексы в БД")
        print(f"   • Разнести БД и бота на разные сервера")
        print(f"   • Использовать асинхронную обработку webhook'ов")


def performance_benchmark():
    """Быстрый тест производительности отдельных операций"""

    print("\n⚡ БЫСТРЫЙ ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ\n")

    # Инициализация
    db.init_schema()
    test_user_id = 9999999
    test_courier_id = 8888888

    db.add_courier("Тест Курьер", test_courier_id, "+79991112233")
    cat_id = db.add_category("Тест")
    db.add_menu_item("Тест Блюдо", 100.0, cat_id)

    operations = [
        ("Сохранение пользователя",
         lambda: db.save_user_pii(test_user_id, name="Тест", phone="+79991112233", address="Тест")),

        ("Чтение пользователя",
         lambda: db.get_user_pii(test_user_id)),

        ("Добавление в корзину",
         lambda: db.add_to_cart(test_user_id, "Тест Блюдо", 100.0, 1)),

        ("Чтение корзины",
         lambda: db.get_cart(test_user_id)),

        ("Создание заказа",
         lambda: db.create_order(test_user_id, f"BENCH_{int(time.time())}", 100.0,
                                "Наличными 💵", test_courier_id, None)),

        ("Чтение заказа",
         lambda: db.get_order(f"BENCH_{int(time.time()-1)}")),

        ("Сохранение рейтинга",
         lambda: db.save_rating(f"RATING_{int(time.time()*1000)}", test_courier_id, test_user_id, 5)),
    ]

    print(f"{'Операция':<30} {'Среднее(мс)':<12} {'Минимум(мс)':<12} {'Максимум(мс)':<12}")
    print("-" * 70)

    for op_name, op_func in operations:
        times = []
        for _ in range(100):  # 100 повторений
            start = time.perf_counter()
            try:
                op_func()
                duration = (time.perf_counter() - start) * 1000
                times.append(duration)
            except:
                pass

        if times:
            avg = statistics.mean(times)
            min_t = min(times)
            max_t = max(times)
            print(f"{op_name:<30} {avg:<12.2f} {min_t:<12.2f} {max_t:<12.2f}")

    # Очистка
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


def main():
    """Главная функция"""
    print("=" * 80)
    print("🚀 НАГРУЗОЧНОЕ ТЕСТИРОВАНИЕ TELEGRAM-БОТА")
    print("=" * 80)
    print("\nВыберите режим тестирования:")
    print("1. Быстрый тест производительности (100 итераций)")
    print("2. Полный нагрузочный тест (1000 пользователей)")
    print("3. Сценарии нагрузки (100 → 2000 пользователей)")
    print("4. Тест стабильности (длительный)")

    choice = input("\nВаш выбор (1-4): ").strip()

    if choice == "1":
        performance_benchmark()

    elif choice == "2":
        tester = LoadTester(num_users=1000, users_per_second=50)
        tester.setup_test_data()
        tester.run_load_test()
        tester.cleanup()

    elif choice == "3":
        tester = ConcurrentLoadTester()
        tester.test_scenarios()

    elif choice == "4":
        print("\n🔄 Запуск теста стабильности на 1 час...")
        print("В тесте будут постоянно создаваться и завершаться пользователи")

        end_time = time.time() + 3600  # 1 час
        cycle = 0

        while time.time() < end_time:
            cycle += 1
            print(f"\nЦикл {cycle}")

            tester = LoadTester(num_users=100, users_per_second=20)
            tester.setup_test_data()
            tester.run_load_test()
            tester.cleanup()

            remaining = int(end_time - time.time())
            if remaining > 0:
                print(f"Осталось времени: {remaining // 60} мин {remaining % 60} сек")
                time.sleep(10)  # Пауза между циклами

        print("\n✅ Тест стабильности завершён!")

    else:
        print("❌ Неверный выбор")


if __name__ == "__main__":
    main()