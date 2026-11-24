from decimal import Decimal
import threading
import time

from django.core.cache import cache
from django.db import OperationalError, connection
from django.test import TransactionTestCase

from bar.models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinkIngredient,
    DrinksCategory,
    StockMovement,
)
from bar.services.exceptions import (
    InsufficientStockError,
    OrderAlreadyClosedError,
)
from bar.services.orders import (
    close_and_pay_order,
    create_order,
    set_order_item,
    toggle_assign_order as toggle_assign_order_service,
)


class OrderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.bartender_one = Bartender.objects.create_user(
            username="conc_bar1",
            password="test_password123",
            staff_id="CONC_BAR1",
            role=Bartender.Role.BARTENDER,
        )
        self.bartender_two = Bartender.objects.create_user(
            username="conc_bar2",
            password="test_password123",
            staff_id="CONC_BAR2",
            role=Bartender.Role.BARTENDER,
        )
        self.manager = Bartender.objects.create_user(
            username="conc_mgr",
            password="test_password123",
            staff_id="CONC_MGR1",
            role=Bartender.Role.MANAGER,
        )
        self.supplier = BarSupplier.objects.create(
            name="Concurrency Supplier",
            phone="+380501112277",
        )
        self.category = DrinksCategory.objects.create(name="Conc Cocktails")
        self.rum = BarIngredient.objects.create(
            name="Conc Rum",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("50.00"),
            cost_per_unit=Decimal("1.0000"),
            supplier=self.supplier,
        )
        self.daiquiri = Drink.objects.create(
            name="Conc Daiquiri",
            price=Decimal("250.00"),
            volume_ml=100,
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=self.daiquiri,
            ingredient=self.rum,
            amount=Decimal("50.00"),
        )

    def tearDown(self):
        cache.clear()

    def test_concurrent_double_pay_deducts_stock_exactly_once(self):
        order = create_order(table_number=1, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.daiquiri.pk,
            quantity=1,
        )

        barrier = threading.Barrier(2)
        successes: list[int] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()

        def pay_worker(worker_index: int):
            try:
                barrier.wait(timeout=5)
                for attempt in range(3):
                    try:
                        paid = close_and_pay_order(
                            order_id=order.pk,
                            actor=self.manager,
                        )
                        with result_lock:
                            successes.append(paid.pk)
                        return
                    except OrderAlreadyClosedError as exc:
                        with result_lock:
                            failures.append(exc)
                        return
                    except OperationalError as exc:
                        if attempt == 2:
                            with result_lock:
                                failures.append(exc)
                            return
                        time.sleep(0.005 * (worker_index + 1) * (attempt + 1))
            finally:
                connection.close()

        threads = [
            threading.Thread(target=pay_worker, args=(0,)),
            threading.Thread(target=pay_worker, args=(1,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.rum.refresh_from_db()
        self.assertEqual(self.rum.stock_quantity, Decimal("0.00"))
        self.assertEqual(
            StockMovement.objects.filter(
                order=order,
                movement_type=StockMovement.MovementType.OUT_ORDER,
            ).count(),
            1,
        )
        with self.assertRaises(OrderAlreadyClosedError):
            close_and_pay_order(order_id=order.pk, actor=self.manager)

    def test_concurrent_orders_sharing_ingredient_never_go_negative(self):
        order_one = create_order(table_number=1, bartender=self.bartender_one)
        set_order_item(
            order_id=order_one.pk,
            drink_id=self.daiquiri.pk,
            quantity=1,
        )
        order_two = create_order(table_number=2, bartender=self.bartender_two)
        set_order_item(
            order_id=order_two.pk,
            drink_id=self.daiquiri.pk,
            quantity=1,
        )

        barrier = threading.Barrier(2)
        successes: list[int] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()

        def pay_worker(
            worker_index: int,
            target_order_id: int,
            actor: Bartender,
        ):
            try:
                barrier.wait(timeout=5)
                for attempt in range(3):
                    try:
                        paid = close_and_pay_order(
                            order_id=target_order_id,
                            actor=actor,
                        )
                        with result_lock:
                            successes.append(paid.pk)
                        return
                    except InsufficientStockError as exc:
                        with result_lock:
                            failures.append(exc)
                        return
                    except OperationalError as exc:
                        if attempt == 2:
                            with result_lock:
                                failures.append(exc)
                            return
                        time.sleep(0.005 * (worker_index + 1) * (attempt + 1))
            finally:
                connection.close()

        threads = [
            threading.Thread(
                target=pay_worker,
                args=(0, order_one.pk, self.bartender_one),
            ),
            threading.Thread(
                target=pay_worker,
                args=(1, order_two.pk, self.bartender_two),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.rum.refresh_from_db()
        self.assertEqual(self.rum.stock_quantity, Decimal("0.00"))

        unpaid_order_id = (
            order_two.pk if successes[0] == order_one.pk else order_one.pk
        )
        retry_actor = (
            self.bartender_two
            if unpaid_order_id == order_two.pk
            else self.bartender_one
        )
        with self.assertRaises(InsufficientStockError):
            close_and_pay_order(order_id=unpaid_order_id, actor=retry_actor)

    def test_concurrent_toggle_assign_assigns_single_winner(self):
        order = create_order(table_number=4)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()

        def assign_worker(worker_index: int, actor: Bartender):
            try:
                barrier.wait(timeout=5)
                for attempt in range(3):
                    try:
                        _, outcome = toggle_assign_order_service(
                            order_id=order.pk,
                            actor=actor,
                        )
                        with result_lock:
                            outcomes.append(outcome)
                        return
                    except OperationalError as exc:
                        if attempt == 2:
                            with result_lock:
                                failures.append(exc)
                            return
                        time.sleep(0.005 * (worker_index + 1) * (attempt + 1))
            finally:
                connection.close()

        threads = [
            threading.Thread(
                target=assign_worker,
                args=(0, self.bartender_one),
            ),
            threading.Thread(
                target=assign_worker,
                args=(1, self.bartender_two),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        order.refresh_from_db()
        self.assertIn(
            order.bartender_id,
            (self.bartender_one.pk, self.bartender_two.pk),
        )
        self.assertEqual(outcomes.count("assigned"), 1)
        self.assertEqual(len(outcomes) + len(failures), 2)
