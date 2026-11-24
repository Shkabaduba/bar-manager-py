import csv
from datetime import timedelta
from decimal import Decimal
import io

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from bar.models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinkIngredient,
    DrinksCategory,
    Order,
)
from bar.services.analytics import (
    export_analytics_csv,
    get_analytics_report,
    get_dashboard_snapshot,
    normalize_period,
    sanitize_csv_cell,
)
from bar.services.inventory import (
    record_adjustment,
    record_stock_in,
    record_writeoff,
)
from bar.services.orders import (
    cancel_order,
    close_and_pay_order,
    create_order,
    set_order_item,
)


class AnalyticsServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="ana_manager",
            password="test_password123",
            staff_id="ANA_MGR01",
            role=Bartender.Role.MANAGER,
            first_name="Olena",
            last_name="Koval",
        )
        self.bartender = Bartender.objects.create_user(
            username="ana_bartender",
            password="test_password123",
            staff_id="ANA_BAR01",
            role=Bartender.Role.BARTENDER,
            first_name="Taras",
            last_name="Sheva",
        )
        self.supplier = BarSupplier.objects.create(
            name="Analytics Supplier",
            phone="+380501112233",
        )
        self.category = DrinksCategory.objects.create(name="Ana Cocktails")

    def tearDown(self):
        cache.clear()

    def _create_drink_with_ingredient(
        self,
        *,
        name: str,
        price: str,
        stock: str,
        unit_cost: str,
        amount: str,
        min_threshold: str = "0.00",
    ) -> tuple[Drink, BarIngredient]:
        ingredient = BarIngredient.objects.create(
            name=f"{name} Base",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal(stock),
            cost_per_unit=Decimal(unit_cost),
            min_stock_threshold=Decimal(min_threshold),
            supplier=self.supplier,
        )
        drink = Drink.objects.create(
            name=name,
            price=Decimal(price),
            volume_ml=100,
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=ingredient,
            amount=Decimal(amount),
        )
        return drink, ingredient

    def test_dashboard_snapshot_computes_kpis_and_caches(self):
        drink, spirit = self._create_drink_with_ingredient(
            name="Dash Negroni",
            price="300.00",
            stock="200.00",
            unit_cost="1.0000",
            amount="50.00",
            min_threshold="300.00",
        )
        BarIngredient.objects.create(
            name="Empty Syrup",
            stock_quantity=Decimal("0.00"),
            cost_per_unit=Decimal("0.5000"),
            supplier=self.supplier,
        )
        create_order(table_number=1, bartender=self.bartender)
        paid_order = create_order(table_number=2, bartender=self.bartender)
        set_order_item(order_id=paid_order.pk, drink_id=drink.pk, quantity=1)
        close_and_pay_order(order_id=paid_order.pk, actor=self.bartender)

        snapshot = get_dashboard_snapshot()
        self.assertEqual(snapshot.num_drinks, 1)
        self.assertEqual(snapshot.num_active_drinks, 1)
        self.assertEqual(snapshot.num_categories, 1)
        self.assertEqual(snapshot.num_suppliers, 1)
        self.assertEqual(snapshot.num_bartenders, 2)
        self.assertEqual(snapshot.active_orders, 1)
        self.assertEqual(snapshot.paid_orders_today, 1)
        self.assertEqual(snapshot.revenue_today, Decimal("300.00"))
        self.assertEqual(snapshot.cogs_today, Decimal("50.00"))
        self.assertEqual(snapshot.gross_profit_today, Decimal("250.00"))
        self.assertEqual(snapshot.out_of_stock_ingredients, 1)
        self.assertEqual(snapshot.low_stock_ingredients, 1)
        self.assertEqual(snapshot.stock_total_value, Decimal("150.00"))

        with self.assertNumQueries(0):
            cached_snapshot = get_dashboard_snapshot()
        self.assertEqual(cached_snapshot, snapshot)

        with self.captureOnCommitCallbacks(execute=True):
            record_stock_in(
                ingredient_id=spirit.pk,
                quantity=Decimal("50.00"),
                unit_cost=Decimal("1.0000"),
            )
        refreshed = get_dashboard_snapshot()
        self.assertEqual(refreshed.stock_total_value, Decimal("200.00"))

    def test_index_view_uses_cached_dashboard_without_session_write(self):
        self.client.force_login(self.bartender)
        get_dashboard_snapshot()
        response = self.client.get(reverse("bar:index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("snapshot", response.context)
        self.assertFalse(self.client.session.modified)

    def test_analytics_report_in_vs_out_margins_and_losses(self):
        drink, spirit = self._create_drink_with_ingredient(
            name="Margin Daiquiri",
            price="250.00",
            stock="0.00",
            unit_cost="0.0000",
            amount="50.00",
        )
        record_stock_in(
            ingredient_id=spirit.pk,
            quantity=Decimal("300.00"),
            unit_cost=Decimal("1.0000"),
            performed_by=self.manager,
            reason="Initial invoice",
        )
        record_writeoff(
            ingredient_id=spirit.pk,
            quantity=Decimal("20.00"),
            reason="Broken glass",
            performed_by=self.manager,
        )
        record_adjustment(
            ingredient_id=spirit.pk,
            actual_quantity=Decimal("270.00"),
            reason="Shortage",
            performed_by=self.manager,
        )
        record_adjustment(
            ingredient_id=spirit.pk,
            actual_quantity=Decimal("280.00"),
            reason="Found bottle",
            performed_by=self.manager,
        )

        cancelled = create_order(table_number=4, bartender=self.bartender)
        cancel_order(
            order_id=cancelled.pk,
            actor=self.bartender,
            reason="Mistake",
        )

        normal_order = create_order(table_number=5, bartender=self.bartender)
        set_order_item(
            order_id=normal_order.pk,
            drink_id=drink.pk,
            quantity=2,
        )
        close_and_pay_order(order_id=normal_order.pk, actor=self.bartender)

        force_order = create_order(table_number=6, bartender=self.bartender)
        set_order_item(order_id=force_order.pk, drink_id=drink.pk, quantity=4)
        close_and_pay_order(
            order_id=force_order.pk,
            actor=self.manager,
            force_override=True,
            override_reason="Extra reserve",
        )

        report = get_analytics_report("7d")
        self.assertEqual(report.paid_orders_count, 2)
        self.assertEqual(report.cancelled_orders_count, 1)
        self.assertEqual(report.force_closed_orders_count, 1)
        self.assertEqual(report.revenue, Decimal("1500.00"))
        self.assertEqual(report.cogs, Decimal("300.00"))
        self.assertEqual(report.gross_margin, Decimal("1200.00"))
        self.assertEqual(report.food_cost_pct, Decimal("20.00"))
        self.assertEqual(report.stock_in_cost, Decimal("300.00"))
        self.assertEqual(report.stock_out_order_cost, Decimal("280.00"))
        self.assertEqual(report.writeoff_loss, Decimal("20.00"))
        self.assertEqual(report.adjustment_shortage_loss, Decimal("10.00"))
        self.assertEqual(report.adjustment_surplus_gain, Decimal("10.00"))
        self.assertEqual(report.total_losses, Decimal("30.00"))
        self.assertEqual(report.net_margin_after_losses, Decimal("1170.00"))
        self.assertEqual(report.current_stock_value, Decimal("0.00"))
        self.assertEqual(len(report.daily_series), 7)

    def test_analytics_report_period_filtering_and_normalization(self):
        self.assertEqual(normalize_period("today"), "today")
        self.assertEqual(normalize_period("30d"), "30d")
        self.assertEqual(normalize_period("invalid"), "7d")
        self.assertEqual(normalize_period(None), "7d")

        drink, _ = self._create_drink_with_ingredient(
            name="Period Sour",
            price="200.00",
            stock="5000.00",
            unit_cost="0.5000",
            amount="50.00",
        )
        now = timezone.now()
        for days_ago in (0, 3, 15, 40):
            order = create_order(table_number=1, bartender=self.bartender)
            set_order_item(order_id=order.pk, drink_id=drink.pk, quantity=1)
            paid = close_and_pay_order(order_id=order.pk, actor=self.bartender)
            Order.objects.filter(pk=paid.pk).update(
                paid_at=now - timedelta(days=days_ago)
            )

        cache.clear()
        today_report = get_analytics_report("today")
        seven_day_report = get_analytics_report("7d")
        thirty_day_report = get_analytics_report("30d")

        self.assertEqual(today_report.paid_orders_count, 1)
        self.assertEqual(len(today_report.daily_series), 1)
        self.assertEqual(seven_day_report.paid_orders_count, 2)
        self.assertEqual(len(seven_day_report.daily_series), 7)
        self.assertEqual(thirty_day_report.paid_orders_count, 3)
        self.assertEqual(len(thirty_day_report.daily_series), 30)

    def test_analytics_top_drinks_and_bartender_ranking(self):
        drinks = []
        for idx in range(1, 7):
            drink, _ = self._create_drink_with_ingredient(
                name=f"Rank Drink {idx}",
                price=f"{100 + idx * 50}.00",
                stock="1000.00",
                unit_cost="0.2000",
                amount="50.00",
            )
            drinks.append(drink)

        order_bar = create_order(table_number=1, bartender=self.bartender)
        for drink in drinks:
            set_order_item(
                order_id=order_bar.pk,
                drink_id=drink.pk,
                quantity=1,
            )
        close_and_pay_order(order_id=order_bar.pk, actor=self.bartender)

        unassigned_order = create_order(table_number=2)
        set_order_item(
            order_id=unassigned_order.pk,
            drink_id=drinks[5].pk,
            quantity=1,
        )
        close_and_pay_order(order_id=unassigned_order.pk, actor=self.manager)

        report = get_analytics_report("7d")
        self.assertEqual(len(report.top_drinks), 5)
        self.assertEqual(report.top_drinks[0].drink_name, "Rank Drink 6")
        self.assertEqual(report.top_drinks[0].portions_sold, 2)
        self.assertEqual(
            [item.drink_name for item in report.top_drinks],
            [
                "Rank Drink 6",
                "Rank Drink 5",
                "Rank Drink 4",
                "Rank Drink 3",
                "Rank Drink 2",
            ],
        )

        self.assertEqual(len(report.bartender_ranking), 2)
        self.assertEqual(
            report.bartender_ranking[0].username,
            self.bartender.username,
        )
        self.assertEqual(
            report.bartender_ranking[0].full_name,
            "Taras Sheva",
        )
        self.assertEqual(
            report.bartender_ranking[1].username,
            self.manager.username,
        )
        self.assertEqual(
            report.bartender_ranking[1].avg_check,
            Decimal("400.00"),
        )

    def test_analytics_report_caches_and_invalidates_on_order_commit(self):
        drink, _ = self._create_drink_with_ingredient(
            name="Cache Martini",
            price="220.00",
            stock="500.00",
            unit_cost="1.0000",
            amount="50.00",
        )
        first_report = get_analytics_report("7d")
        self.assertEqual(first_report.paid_orders_count, 0)

        with self.assertNumQueries(0):
            cached_report = get_analytics_report("7d")
        self.assertEqual(cached_report, first_report)

        with self.captureOnCommitCallbacks(execute=True):
            order = create_order(table_number=7, bartender=self.bartender)
            set_order_item(order_id=order.pk, drink_id=drink.pk, quantity=1)
            close_and_pay_order(order_id=order.pk, actor=self.bartender)

        updated_report = get_analytics_report("7d")
        self.assertEqual(updated_report.paid_orders_count, 1)
        self.assertEqual(updated_report.revenue, Decimal("220.00"))

    def test_sanitize_csv_cell_prevents_formula_injection(self):
        self.assertEqual(sanitize_csv_cell(None), "")
        self.assertEqual(sanitize_csv_cell(42), "42")
        self.assertEqual(sanitize_csv_cell(Decimal("-15.50")), "-15.50")
        self.assertEqual(sanitize_csv_cell("Normal Drink"), "Normal Drink")
        for prefix in ("=", "+", "-", "@", "\t", "\r", "  ="):
            raw_cell = f"{prefix}SUM(A1:A2)"
            self.assertEqual(sanitize_csv_cell(raw_cell), f"'{raw_cell}")

    def test_export_analytics_csv_sanitizes_malicious_names(self):
        drink, spirit = self._create_drink_with_ingredient(
            name="=HYPERLINK('http://evil.test','Click')",
            price="180.00",
            stock="300.00",
            unit_cost="1.0000",
            amount="50.00",
        )
        record_writeoff(
            ingredient_id=spirit.pk,
            quantity=Decimal("10.00"),
            reason="+cmd|' /C calc'!A0",
            performed_by=self.manager,
        )
        order = create_order(table_number=3, bartender=self.bartender)
        set_order_item(order_id=order.pk, drink_id=drink.pk, quantity=1)
        close_and_pay_order(order_id=order.pk, actor=self.bartender)

        csv_content = export_analytics_csv("7d")
        rows = list(csv.reader(io.StringIO(csv_content)))
        flat_cells = [cell for row in rows for cell in row]
        self.assertIn(
            "'=HYPERLINK('http://evil.test','Click')",
            flat_cells,
        )
        self.assertIn("'+cmd|' /C calc'!A0", flat_cells)
        self.assertIn("180.00", flat_cells)


class QueryPerformanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="perf_manager",
            password="test_password123",
            staff_id="PERF_MGR1",
            role=Bartender.Role.MANAGER,
        )
        self.bartender = Bartender.objects.create_user(
            username="perf_bartender",
            password="test_password123",
            staff_id="PERF_BAR1",
            role=Bartender.Role.BARTENDER,
        )
        self.supplier = BarSupplier.objects.create(
            name="Perf Supplier",
            phone="+380501119900",
        )
        self.category = DrinksCategory.objects.create(name="Perf Cocktails")
        self.ingredients = [
            BarIngredient.objects.create(
                name=f"Perf Ing {idx}",
                unit=BarIngredient.Unit.ML,
                stock_quantity=Decimal("2000.00"),
                cost_per_unit=Decimal("1.0000"),
                supplier=self.supplier,
            )
            for idx in range(6)
        ]

    def tearDown(self):
        cache.clear()

    def _create_drink_with_ingredients(
        self,
        drink_name: str,
        ing_count: int,
    ) -> Drink:
        drink = Drink.objects.create(
            name=drink_name,
            price=Decimal("250.00"),
            volume_ml=150,
            category=self.category,
        )
        for ingredient in self.ingredients[:ing_count]:
            DrinkIngredient.objects.create(
                drink=drink,
                ingredient=ingredient,
                amount=Decimal("30.00"),
            )
        return drink

    def test_dashboard_index_warm_cache_uses_minimal_queries_no_session_write(
        self,
    ):
        self.client.force_login(self.bartender)
        get_dashboard_snapshot()

        with CaptureQueriesContext(connection) as query_ctx:
            response = self.client.get(reverse("bar:index"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(query_ctx.captured_queries), 2)
        for query in query_ctx.captured_queries:
            sql_text = query["sql"]
            self.assertFalse(
                "UPDATE" in sql_text and "django_session" in sql_text
            )
            if '"bar_bartender"' not in sql_text:
                self.assertNotIn('"bar_', sql_text)

    def test_order_list_constant_queries_with_sql_annotations(self):
        drink_one = self._create_drink_with_ingredients("Ord List 1", 2)
        drink_two = self._create_drink_with_ingredients("Ord List 2", 2)
        for table_num in range(1, 3):
            order = create_order(
                table_number=table_num,
                bartender=self.bartender,
            )
            set_order_item(
                order_id=order.pk,
                drink_id=drink_one.pk,
                quantity=2,
            )

        self.client.force_login(self.bartender)
        with CaptureQueriesContext(connection) as small_ctx:
            small_resp = self.client.get(reverse("bar:order-list"))
        self.assertEqual(small_resp.status_code, 200)
        baseline_count = len(small_ctx.captured_queries)
        self.assertLessEqual(baseline_count, 5)
        self.assertFalse(
            any(
                '"bar_drink"' in q["sql"]
                for q in small_ctx.captured_queries
            )
        )

        for table_num in range(3, 7):
            order = create_order(
                table_number=table_num,
                bartender=self.bartender,
            )
            set_order_item(
                order_id=order.pk,
                drink_id=drink_one.pk,
                quantity=1,
            )
            set_order_item(
                order_id=order.pk,
                drink_id=drink_two.pk,
                quantity=2,
            )

        with self.assertNumQueries(baseline_count):
            large_resp = self.client.get(reverse("bar:order-list"))
        self.assertEqual(large_resp.status_code, 200)

    def test_drink_list_constant_queries_with_prefetched_costing(self):
        for idx in range(2):
            self._create_drink_with_ingredients(f"List Drink {idx}", 2)

        self.client.force_login(self.bartender)
        with CaptureQueriesContext(connection) as small_ctx:
            small_resp = self.client.get(reverse("bar:drink-list"))
        self.assertEqual(small_resp.status_code, 200)
        baseline_count = len(small_ctx.captured_queries)
        self.assertLessEqual(baseline_count, 7)

        for idx in range(2, 6):
            self._create_drink_with_ingredients(f"List Drink {idx}", 3)

        with self.assertNumQueries(baseline_count):
            large_resp = self.client.get(reverse("bar:drink-list"))
        self.assertEqual(large_resp.status_code, 200)

    def test_drink_detail_and_bartender_detail_constant_queries(self):
        small_drink = self._create_drink_with_ingredients("Detail Small", 1)
        large_drink = self._create_drink_with_ingredients("Detail Large", 6)

        self.client.force_login(self.manager)
        with CaptureQueriesContext(connection) as small_drink_ctx:
            small_drink_resp = self.client.get(
                reverse("bar:drink-detail", args=[small_drink.pk])
            )
        self.assertEqual(small_drink_resp.status_code, 200)

        with self.assertNumQueries(len(small_drink_ctx.captured_queries)):
            large_drink_resp = self.client.get(
                reverse("bar:drink-detail", args=[large_drink.pk])
            )
        self.assertEqual(large_drink_resp.status_code, 200)

        first_order = create_order(table_number=1, bartender=self.bartender)
        set_order_item(
            order_id=first_order.pk,
            drink_id=small_drink.pk,
            quantity=1,
        )
        close_and_pay_order(order_id=first_order.pk, actor=self.bartender)

        with CaptureQueriesContext(connection) as small_staff_ctx:
            small_staff_resp = self.client.get(
                reverse("bar:bartender-detail", args=[self.bartender.pk])
            )
        self.assertEqual(small_staff_resp.status_code, 200)

        for table_num in range(2, 6):
            next_order = create_order(
                table_number=table_num,
                bartender=self.bartender,
            )
            set_order_item(
                order_id=next_order.pk,
                drink_id=small_drink.pk,
                quantity=1,
            )
            set_order_item(
                order_id=next_order.pk,
                drink_id=large_drink.pk,
                quantity=1,
            )
            close_and_pay_order(
                order_id=next_order.pk,
                actor=self.bartender,
            )

        with self.assertNumQueries(len(small_staff_ctx.captured_queries)):
            large_staff_resp = self.client.get(
                reverse("bar:bartender-detail", args=[self.bartender.pk])
            )
        self.assertEqual(large_staff_resp.status_code, 200)

    def test_cache_invalidates_across_crud_stock_and_order_mutations(self):
        drink = self._create_drink_with_ingredients("Cache Mutation Gin", 1)
        initial_snap = get_dashboard_snapshot()
        initial_report = get_analytics_report("7d")
        self.assertEqual(initial_snap.num_categories, 1)
        self.assertEqual(initial_report.paid_orders_count, 0)

        with self.assertNumQueries(0):
            self.assertEqual(get_dashboard_snapshot(), initial_snap)
            self.assertEqual(get_analytics_report("7d"), initial_report)

        self.client.force_login(self.manager)
        self.client.post(
            reverse("bar:category-create"),
            data={"name": "Perf Shots", "is_alcohol": True},
        )
        self.assertEqual(get_dashboard_snapshot().num_categories, 2)

        with self.captureOnCommitCallbacks(execute=True):
            record_stock_in(
                ingredient_id=self.ingredients[0].pk,
                quantity=Decimal("100.00"),
                unit_cost=Decimal("2.0000"),
                performed_by=self.manager,
            )
        self.assertGreater(
            get_dashboard_snapshot().stock_total_value,
            initial_snap.stock_total_value,
        )

        with self.captureOnCommitCallbacks(execute=True):
            order = create_order(table_number=9, bartender=self.bartender)
            set_order_item(
                order_id=order.pk,
                drink_id=drink.pk,
                quantity=1,
            )
            close_and_pay_order(order_id=order.pk, actor=self.bartender)

        self.assertEqual(
            get_dashboard_snapshot().revenue_today,
            Decimal("250.00"),
        )
        self.assertEqual(get_analytics_report("7d").paid_orders_count, 1)
