from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bar.models import (
    AuditLog,
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinkIngredient,
    DrinksCategory,
    Order,
    OrderItem,
    StockMovement,
)
from bar.services.cache import (
    get_analytics_cache_version,
    invalidate_analytics_cache,
)
from bar.services.exceptions import (
    InsufficientStockError,
    InvalidQuantityError,
    OptimisticLockError,
    OrderAlreadyClosedError,
    OrderStateError,
)
from bar.services.inventory import (
    record_adjustment,
    record_stock_in,
    record_writeoff,
)
from bar.services.orders import (
    add_order_item,
    cancel_order,
    close_and_pay_order,
    create_order,
    remove_order_item,
    set_order_item,
    toggle_assign_order as toggle_assign_order_service,
)


class PrivateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test_username",
            password="test_password123",
            staff_id="Acf",
            role=Bartender.Role.MANAGER,
        )
        self.client.force_login(self.user)

    def test_create_drink(self):
        category = DrinksCategory.objects.create(name="Cocktails")
        supplier = BarSupplier.objects.create(
            name="Metro", phone="+380501112233"
        )
        ingredient = BarIngredient.objects.create(
            name="Rum", stock_quantity=10, supplier=supplier
        )
        form_data = {
            "name": "Daiquiri",
            "price": "11.50",
            "volume_ml": 200,
            "target_food_cost_pct": "25.00",
            "is_active": True,
            "category": category.id,
            "recipe_items-TOTAL_FORMS": "1",
            "recipe_items-INITIAL_FORMS": "0",
            "recipe_items-MIN_NUM_FORMS": "0",
            "recipe_items-MAX_NUM_FORMS": "1000",
            "recipe_items-0-ingredient": str(ingredient.id),
            "recipe_items-0-amount": "50.00",
        }
        response = self.client.post(
            reverse("bar:drink-create"),
            data=form_data,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Drink.objects.filter(name="Daiquiri").exists())

    def test_update_drink(self):
        category = DrinksCategory.objects.create(name="Cocktails")
        supplier = BarSupplier.objects.create(
            name="Metro", phone="+380501112233"
        )
        ingredient = BarIngredient.objects.create(
            name="Gin", stock_quantity=5, supplier=supplier
        )
        drink = Drink.objects.create(
            name="Old Name", price=10.0, volume_ml=250, category=category
        )
        form_data = {
            "name": "New Name",
            "price": "15.00",
            "volume_ml": 300,
            "target_food_cost_pct": "25.00",
            "is_active": True,
            "category": category.id,
            "recipe_items-TOTAL_FORMS": "1",
            "recipe_items-INITIAL_FORMS": "0",
            "recipe_items-MIN_NUM_FORMS": "0",
            "recipe_items-MAX_NUM_FORMS": "1000",
            "recipe_items-0-ingredient": str(ingredient.id),
            "recipe_items-0-amount": "50.00",
        }
        response = self.client.post(
            reverse("bar:drink-update", args=[drink.id]), data=form_data
        )
        self.assertEqual(response.status_code, 302)
        drink.refresh_from_db()
        self.assertEqual(drink.name, "New Name")

    def test_delete_drink(self):
        category = DrinksCategory.objects.create(name="Cocktails")
        drink = Drink.objects.create(
            name="To Delete", price=10.0, volume_ml=250, category=category
        )
        response = self.client.post(
            reverse("bar:drink-delete", args=[drink.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Drink.objects.filter(id=drink.id).exists())

    def test_search_categories(self):
        cat1 = DrinksCategory.objects.create(
            name="Cocktails",
            is_alcohol=True,
        )
        cat2 = DrinksCategory.objects.create(
            name="Lemonades",
            is_alcohol=False,
        )
        response = self.client.get(
            reverse("bar:category-list"), {"name": "Cock"}
        )
        self.assertIn(cat1, response.context["category_list"])
        self.assertNotIn(cat2, response.context["category_list"])

    def test_retrieve_lists(self):
        urls = [
            reverse("bar:category-list"),
            reverse("bar:drink-list"),
            reverse("bar:bartender-list"),
        ]
        for target_url in urls:
            response = self.client.get(target_url)
            self.assertEqual(response.status_code, 200)

    def test_search_drinks(self):
        category = DrinksCategory.objects.create(name="Cocktails")
        drink1 = Drink.objects.create(
            name="Mojito", price=10.0, volume_ml=250, category=category
        )
        drink2 = Drink.objects.create(
            name="Negroni", price=12.0, volume_ml=200, category=category
        )
        response = self.client.get(
            reverse("bar:drink-list"), {"name": "Moj"}
        )
        self.assertIn(drink1, response.context["drink_list"])
        self.assertNotIn(drink2, response.context["drink_list"])

    def test_search_bartenders(self):
        bartender2 = get_user_model().objects.create_user(
            username="john_wick",
            password="test_password123",
            staff_id="STAFF_999",
        )
        response = self.client.get(
            reverse("bar:bartender-list"), {"username": "john"}
        )
        self.assertIn(bartender2, response.context["bartender_list"])
        self.assertNotIn(self.user, response.context["bartender_list"])

    def test_toggle_assign_order(self):
        order = Order.objects.create(table_number=5)
        self.client.post(reverse("bar:toggle-assign-order", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.bartender, self.user)

        self.client.post(reverse("bar:toggle-assign-order", args=[order.id]))
        order.refresh_from_db()
        self.assertIsNone(order.bartender)

    def test_search_suppliers(self):
        supplier1 = BarSupplier.objects.create(
            name="Metro Cash & Carry", phone="+380501112233"
        )
        supplier2 = BarSupplier.objects.create(
            name="WineBureau", phone="+380502223344"
        )
        response = self.client.get(
            reverse("bar:supplier-list"), {"name": "Metro"}
        )
        self.assertIn(supplier1, response.context["supplier_list"])
        self.assertNotIn(supplier2, response.context["supplier_list"])

    def test_create_supplier(self):
        data = {
            "name": "Local Craft Spirits",
            "phone": "+380509998877",
            "email": "craft@bar.com",
        }
        response = self.client.post(reverse("bar:supplier-create"), data=data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            BarSupplier.objects.filter(name="Local Craft Spirits").exists()
        )

    def test_update_supplier(self):
        supplier = BarSupplier.objects.create(
            name="Old Supplier", phone="+380501112233"
        )
        data = {
            "name": "Updated Supplier",
            "phone": "+380501112233",
            "email": "updated@bar.com",
        }
        response = self.client.post(
            reverse("bar:supplier-update", args=[supplier.id]), data=data
        )
        self.assertEqual(response.status_code, 302)
        supplier.refresh_from_db()
        self.assertEqual(supplier.name, "Updated Supplier")

    def test_delete_supplier(self):
        supplier = BarSupplier.objects.create(
            name="Delete Me Supplier", phone="+380500000000"
        )
        response = self.client.post(
            reverse("bar:supplier-delete", args=[supplier.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BarSupplier.objects.filter(id=supplier.id).exists()
        )

    def test_search_ingredients(self):
        supplier = BarSupplier.objects.create(
            name="Syrup World", phone="+380503334455"
        )
        ing1 = BarIngredient.objects.create(
            name="Lime Juice", stock_quantity=10, supplier=supplier
        )
        ing2 = BarIngredient.objects.create(
            name="Sugar Syrup", stock_quantity=15, supplier=supplier
        )
        response = self.client.get(
            reverse("bar:ingredient-list"), {"name": "Lime"}
        )
        self.assertIn(ing1, response.context["ingredient_list"])
        self.assertNotIn(ing2, response.context["ingredient_list"])

    def test_create_ingredient(self):
        supplier = BarSupplier.objects.create(
            name="Distributor X", phone="+380504445566"
        )
        data = {
            "name": "Angostura Bitters",
            "unit": BarIngredient.Unit.ML,
            "min_stock_threshold": "10.00",
            "stock_quantity": 4,
            "supplier": supplier.id,
        }
        response = self.client.post(
            reverse("bar:ingredient-create"), data=data
        )
        self.assertEqual(response.status_code, 302)
        created = BarIngredient.objects.get(name="Angostura Bitters")
        self.assertEqual(created.stock_quantity, Decimal("0.00"))

    def test_update_ingredient(self):
        supplier = BarSupplier.objects.create(
            name="Distributor Y", phone="+380504445577"
        )
        ingredient = BarIngredient.objects.create(
            name="Vodka", stock_quantity=8, supplier=supplier
        )
        data = {
            "name": "Premium Vodka",
            "unit": BarIngredient.Unit.ML,
            "min_stock_threshold": "5.00",
            "stock_quantity": 12,
            "supplier": supplier.id,
        }
        response = self.client.post(
            reverse("bar:ingredient-update", args=[ingredient.id]), data=data
        )
        self.assertEqual(response.status_code, 302)
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.name, "Premium Vodka")
        self.assertEqual(ingredient.stock_quantity, Decimal("8.00"))

    def test_delete_ingredient(self):
        supplier = BarSupplier.objects.create(
            name="Distributor Z", phone="+380504445588"
        )
        ingredient = BarIngredient.objects.create(
            name="Tonic Water", stock_quantity=20, supplier=supplier
        )
        response = self.client.post(
            reverse("bar:ingredient-delete", args=[ingredient.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BarIngredient.objects.filter(id=ingredient.id).exists()
        )


class InventoryServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="inv_manager",
            password="test_password123",
            staff_id="INV_MGR01",
            role=Bartender.Role.MANAGER,
        )
        self.supplier = BarSupplier.objects.create(
            name="Inventory Supplier",
            phone="+380501112288",
        )

    def tearDown(self):
        cache.clear()

    def test_record_stock_in_from_zero_sets_cost_and_movement(self):
        ingredient = BarIngredient.objects.create(
            name="Fresh Gin",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("0.00"),
            cost_per_unit=Decimal("0.0000"),
            supplier=self.supplier,
        )
        movement = record_stock_in(
            ingredient_id=ingredient.pk,
            quantity=Decimal("1000.00"),
            unit_cost=Decimal("0.8500"),
            performed_by=self.manager,
            reason="Invoice #101",
        )
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.stock_quantity, Decimal("1000.00"))
        self.assertEqual(ingredient.cost_per_unit, Decimal("0.8500"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.IN)
        self.assertEqual(movement.quantity_delta, Decimal("1000.00"))
        self.assertEqual(movement.balance_after, Decimal("1000.00"))
        self.assertEqual(movement.unit_cost, Decimal("0.8500"))
        self.assertEqual(movement.total_cost, Decimal("850.00"))
        self.assertEqual(movement.performed_by, self.manager)

    def test_record_stock_in_recalculates_weighted_average_cost(self):
        ingredient = BarIngredient.objects.create(
            name="Weighted Vodka",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("100.00"),
            cost_per_unit=Decimal("2.0000"),
            supplier=self.supplier,
        )
        movement = record_stock_in(
            ingredient_id=ingredient.pk,
            quantity=Decimal("200.00"),
            unit_cost=Decimal("5.0000"),
            performed_by=self.manager,
            reason="Batch #2",
        )
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.stock_quantity, Decimal("300.00"))
        self.assertEqual(ingredient.cost_per_unit, Decimal("4.0000"))
        self.assertEqual(movement.balance_after, Decimal("300.00"))
        self.assertEqual(movement.total_cost, Decimal("1000.00"))

    def test_record_stock_in_rejects_invalid_quantity_or_negative_cost(self):
        ingredient = BarIngredient.objects.create(
            name="Guard Rum",
            stock_quantity=Decimal("50.00"),
            supplier=self.supplier,
        )
        with self.assertRaises(InvalidQuantityError):
            record_stock_in(
                ingredient_id=ingredient.pk,
                quantity=Decimal("0.00"),
                unit_cost=Decimal("1.0000"),
            )
        with self.assertRaises(InvalidQuantityError):
            record_stock_in(
                ingredient_id=ingredient.pk,
                quantity=Decimal("50.00"),
                unit_cost=Decimal("-0.1000"),
            )

    def test_record_writeoff_deducts_stock_and_logs_audit(self):
        ingredient = BarIngredient.objects.create(
            name="Spilled Tequila",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("500.00"),
            cost_per_unit=Decimal("1.5000"),
            supplier=self.supplier,
        )
        movement = record_writeoff(
            ingredient_id=ingredient.pk,
            quantity=Decimal("100.00"),
            reason="Broken bottle",
            performed_by=self.manager,
            ip_address="127.0.0.1",
        )
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.stock_quantity, Decimal("400.00"))
        self.assertEqual(
            movement.movement_type,
            StockMovement.MovementType.WRITEOFF,
        )
        self.assertEqual(movement.quantity_delta, Decimal("-100.00"))
        self.assertEqual(movement.balance_after, Decimal("400.00"))
        self.assertEqual(movement.total_cost, Decimal("150.00"))

        audit_log = AuditLog.objects.get(
            action="STOCK_WRITEOFF",
            target_id=str(ingredient.pk),
        )
        self.assertEqual(audit_log.actor, self.manager)
        self.assertEqual(audit_log.ip_address, "127.0.0.1")
        self.assertEqual(audit_log.metadata["reason"], "Broken bottle")

    def test_record_writeoff_blocks_insufficient_stock_and_blank_reason(self):
        ingredient = BarIngredient.objects.create(
            name="Low Vermouth",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("40.00"),
            cost_per_unit=Decimal("1.0000"),
            supplier=self.supplier,
        )
        with self.assertRaises(InsufficientStockError) as err_ctx:
            record_writeoff(
                ingredient_id=ingredient.pk,
                quantity=Decimal("60.00"),
                reason="Spoiled",
                performed_by=self.manager,
            )
        self.assertEqual(len(err_ctx.exception.deficits), 1)
        deficit = err_ctx.exception.deficits[0]
        self.assertEqual(deficit.shortfall, Decimal("20.00"))
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.stock_quantity, Decimal("40.00"))
        self.assertFalse(
            AuditLog.objects.filter(action="STOCK_WRITEOFF").exists()
        )

        with self.assertRaises(InvalidQuantityError):
            record_writeoff(
                ingredient_id=ingredient.pk,
                quantity=Decimal("10.00"),
                reason="   ",
            )

    def test_record_adjustment_handles_shortage_and_surplus_with_audit(self):
        ingredient = BarIngredient.objects.create(
            name="Audit Syrup",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("200.00"),
            cost_per_unit=Decimal("0.5000"),
            supplier=self.supplier,
        )
        shortage_move = record_adjustment(
            ingredient_id=ingredient.pk,
            actual_quantity=Decimal("175.00"),
            reason="Night shift count",
            performed_by=self.manager,
        )
        self.assertEqual(shortage_move.quantity_delta, Decimal("-25.00"))
        self.assertEqual(shortage_move.balance_after, Decimal("175.00"))
        self.assertEqual(shortage_move.total_cost, Decimal("12.50"))

        surplus_move = record_adjustment(
            ingredient_id=ingredient.pk,
            actual_quantity=Decimal("190.00"),
            reason="Found unopened bottle",
            performed_by=self.manager,
        )
        self.assertEqual(surplus_move.quantity_delta, Decimal("15.00"))
        self.assertEqual(surplus_move.balance_after, Decimal("190.00"))
        self.assertEqual(surplus_move.total_cost, Decimal("7.50"))
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.stock_quantity, Decimal("190.00"))
        self.assertEqual(
            AuditLog.objects.filter(action="STOCK_ADJUSTMENT").count(),
            2,
        )

    def test_record_adjustment_allows_zero_delta_and_rejects_invalid(self):
        ingredient = BarIngredient.objects.create(
            name="Exact Bitters",
            stock_quantity=Decimal("120.00"),
            cost_per_unit=Decimal("2.0000"),
            supplier=self.supplier,
        )
        confirm_move = record_adjustment(
            ingredient_id=ingredient.pk,
            actual_quantity=Decimal("120.00"),
            reason="Count verified",
            performed_by=self.manager,
        )
        self.assertEqual(confirm_move.quantity_delta, Decimal("0.00"))
        self.assertEqual(confirm_move.balance_after, Decimal("120.00"))
        self.assertEqual(confirm_move.total_cost, Decimal("0.00"))

        with self.assertRaises(InvalidQuantityError):
            record_adjustment(
                ingredient_id=ingredient.pk,
                actual_quantity=Decimal("-5.00"),
                reason="Impossible negative",
            )
        with self.assertRaises(InvalidQuantityError):
            record_adjustment(
                ingredient_id=ingredient.pk,
                actual_quantity=Decimal("100.00"),
                reason="",
            )

    def test_inventory_operations_invalidate_cache_only_on_commit(self):
        ingredient = BarIngredient.objects.create(
            name="Cache Ingredient",
            stock_quantity=Decimal("10.00"),
            cost_per_unit=Decimal("1.0000"),
            supplier=self.supplier,
        )
        initial_version = get_analytics_cache_version()
        self.assertEqual(initial_version, 1)

        with self.captureOnCommitCallbacks(execute=True):
            record_stock_in(
                ingredient_id=ingredient.pk,
                quantity=Decimal("5.00"),
                unit_cost=Decimal("2.0000"),
            )
        version_after_commit = get_analytics_cache_version()
        self.assertEqual(version_after_commit, 2)

        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(InsufficientStockError):
                record_writeoff(
                    ingredient_id=ingredient.pk,
                    quantity=Decimal("100.00"),
                    reason="Should fail",
                )
        self.assertEqual(get_analytics_cache_version(), 2)

        cache.clear()
        invalidate_analytics_cache()
        self.assertEqual(get_analytics_cache_version(), 2)


class OrderServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="ord_manager",
            password="test_password123",
            staff_id="ORD_MGR01",
            role=Bartender.Role.MANAGER,
        )
        self.bartender_one = Bartender.objects.create_user(
            username="ord_bartender1",
            password="test_password123",
            staff_id="ORD_BAR01",
            role=Bartender.Role.BARTENDER,
        )
        self.bartender_two = Bartender.objects.create_user(
            username="ord_bartender2",
            password="test_password123",
            staff_id="ORD_BAR02",
            role=Bartender.Role.BARTENDER,
        )
        self.supplier = BarSupplier.objects.create(
            name="Order Supplier",
            phone="+380501112211",
        )
        self.category = DrinksCategory.objects.create(name="Order Cocktails")
        self.gin = BarIngredient.objects.create(
            name="Order Gin",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("500.00"),
            cost_per_unit=Decimal("1.0000"),
            supplier=self.supplier,
        )
        self.vermouth = BarIngredient.objects.create(
            name="Order Vermouth",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("300.00"),
            cost_per_unit=Decimal("0.5000"),
            supplier=self.supplier,
        )
        self.negroni = Drink.objects.create(
            name="Order Negroni",
            price=Decimal("350.00"),
            volume_ml=90,
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=self.negroni,
            ingredient=self.gin,
            amount=Decimal("40.00"),
        )
        DrinkIngredient.objects.create(
            drink=self.negroni,
            ingredient=self.vermouth,
            amount=Decimal("30.00"),
        )

    def tearDown(self):
        cache.clear()

    def test_create_order_and_item_mutations_bump_version(self):
        order = create_order(table_number=12, bartender=self.bartender_one)
        self.assertEqual(order.status, Order.Status.IN_PROGRESS)
        self.assertEqual(order.version, 1)

        order_item = add_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            delta=2,
            expected_version=1,
        )
        order.refresh_from_db()
        self.assertEqual(order.version, 2)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.unit_price_snapshot, Decimal("350.00"))
        self.assertEqual(order_item.unit_cost_snapshot, Decimal("55.0000"))

        updated_item = set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=3,
            expected_version=2,
        )
        order.refresh_from_db()
        self.assertEqual(order.version, 3)
        self.assertEqual(updated_item.quantity, 3)

        removed = remove_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            expected_version=3,
        )
        order.refresh_from_db()
        self.assertTrue(removed)
        self.assertEqual(order.version, 4)
        self.assertEqual(order.items.count(), 0)

    def test_optimistic_lock_rejects_stale_version(self):
        order = create_order(table_number=5, bartender=self.bartender_one)
        add_order_item(order_id=order.pk, drink_id=self.negroni.pk, delta=1)
        order.refresh_from_db()
        self.assertEqual(order.version, 2)

        with self.assertRaises(OptimisticLockError):
            set_order_item(
                order_id=order.pk,
                drink_id=self.negroni.pk,
                quantity=5,
                expected_version=1,
            )

    def test_toggle_assign_order_transitions_and_blocks_other_and_closed(self):
        order = create_order(table_number=8)
        self.assertEqual(order.status, Order.Status.OPEN)

        order, outcome = toggle_assign_order_service(
            order_id=order.pk,
            actor=self.bartender_one,
        )
        self.assertEqual(outcome, "assigned")
        self.assertEqual(order.bartender, self.bartender_one)
        self.assertEqual(order.status, Order.Status.IN_PROGRESS)

        order, other_outcome = toggle_assign_order_service(
            order_id=order.pk,
            actor=self.bartender_two,
        )
        self.assertEqual(other_outcome, "taken_by_other")
        self.assertEqual(order.bartender, self.bartender_one)

        order, release_outcome = toggle_assign_order_service(
            order_id=order.pk,
            actor=self.bartender_one,
        )
        self.assertEqual(release_outcome, "unassigned")
        self.assertIsNone(order.bartender)
        self.assertEqual(order.status, Order.Status.OPEN)

        cancel_order(
            order_id=order.pk,
            actor=self.manager,
            reason="Guest left",
        )
        with self.assertRaises(OrderAlreadyClosedError):
            toggle_assign_order_service(
                order_id=order.pk,
                actor=self.bartender_one,
            )

    def test_close_and_pay_order_deducts_stock_and_invalidates_cache(self):
        order = create_order(table_number=1, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=2,
        )
        version_before = get_analytics_cache_version()

        with self.captureOnCommitCallbacks(execute=True):
            paid_order = close_and_pay_order(
                order_id=order.pk,
                actor=self.bartender_one,
            )

        self.assertEqual(paid_order.status, Order.Status.PAID)
        self.assertTrue(paid_order.is_paid)
        self.assertIsNotNone(paid_order.paid_at)
        self.assertEqual(paid_order.closed_by, self.bartender_one)
        self.assertEqual(
            paid_order.total_revenue_snapshot,
            Decimal("700.00"),
        )
        self.assertEqual(
            paid_order.total_cost_snapshot,
            Decimal("110.00"),
        )

        self.gin.refresh_from_db()
        self.vermouth.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("420.00"))
        self.assertEqual(self.vermouth.stock_quantity, Decimal("240.00"))
        self.assertEqual(
            StockMovement.objects.filter(
                order=paid_order,
                movement_type=StockMovement.MovementType.OUT_ORDER,
            ).count(),
            2,
        )
        self.assertEqual(get_analytics_cache_version(), version_before + 1)

    def test_close_and_pay_order_strict_stop_list_rolls_back(self):
        self.vermouth.stock_quantity = Decimal("20.00")
        self.vermouth.save(update_fields=["stock_quantity"])

        order = create_order(table_number=2, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=1,
        )

        with self.assertRaises(InsufficientStockError) as err_ctx:
            close_and_pay_order(order_id=order.pk, actor=self.bartender_one)

        self.assertEqual(len(err_ctx.exception.deficits), 1)
        deficit = err_ctx.exception.deficits[0]
        self.assertEqual(deficit.ingredient_id, self.vermouth.pk)
        self.assertEqual(deficit.shortfall, Decimal("10.00"))

        order.refresh_from_db()
        self.gin.refresh_from_db()
        self.vermouth.refresh_from_db()
        self.assertEqual(order.status, Order.Status.IN_PROGRESS)
        self.assertFalse(order.is_paid)
        self.assertEqual(self.gin.stock_quantity, Decimal("500.00"))
        self.assertEqual(self.vermouth.stock_quantity, Decimal("20.00"))

    def test_close_and_pay_order_double_pay_is_idempotent(self):
        order = create_order(table_number=3, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=1,
        )
        close_and_pay_order(order_id=order.pk, actor=self.bartender_one)

        with self.assertRaises(OrderAlreadyClosedError):
            close_and_pay_order(order_id=order.pk, actor=self.bartender_one)

        self.gin.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("460.00"))

    def test_bartender_rbac_for_pay_and_force_close(self):
        order = create_order(table_number=4, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=1,
        )
        with self.assertRaises(PermissionDenied):
            close_and_pay_order(order_id=order.pk, actor=self.bartender_two)

        self.vermouth.stock_quantity = Decimal("10.00")
        self.vermouth.save(update_fields=["stock_quantity"])
        with self.assertRaises(PermissionDenied):
            close_and_pay_order(
                order_id=order.pk,
                actor=self.bartender_one,
                force_override=True,
                override_reason="Try override",
            )

    def test_manager_force_close_clamps_to_zero_and_writes_audit(self):
        self.vermouth.stock_quantity = Decimal("15.00")
        self.vermouth.save(update_fields=["stock_quantity"])

        order = create_order(table_number=6, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=1,
        )

        with self.assertRaises(InvalidQuantityError):
            close_and_pay_order(
                order_id=order.pk,
                actor=self.manager,
                force_override=True,
                override_reason="   ",
            )

        paid_order = close_and_pay_order(
            order_id=order.pk,
            actor=self.manager,
            force_override=True,
            override_reason="VIP guest bottle opened off-ledger",
            ip_address="127.0.0.1",
        )
        self.assertEqual(paid_order.status, Order.Status.PAID)
        self.assertEqual(paid_order.override_by, self.manager)

        self.gin.refresh_from_db()
        self.vermouth.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("460.00"))
        self.assertEqual(self.vermouth.stock_quantity, Decimal("0.00"))

        vermouth_move = StockMovement.objects.get(
            order=paid_order,
            ingredient=self.vermouth,
        )
        self.assertEqual(vermouth_move.quantity_delta, Decimal("-15.00"))
        self.assertEqual(vermouth_move.shortfall_quantity, Decimal("15.00"))
        self.assertEqual(vermouth_move.balance_after, Decimal("0.00"))

        audit_log = AuditLog.objects.get(
            action="FORCE_CLOSE_ORDER",
            target_id=str(paid_order.pk),
        )
        self.assertEqual(audit_log.actor, self.manager)
        self.assertEqual(len(audit_log.metadata["deficits"]), 1)

    def test_cancel_order_locks_order_and_logs_audit(self):
        order = create_order(table_number=9, bartender=self.bartender_one)
        with self.assertRaises(PermissionDenied):
            cancel_order(order_id=order.pk, actor=self.bartender_two)

        cancelled = cancel_order(
            order_id=order.pk,
            actor=self.bartender_one,
            reason="Wrong table",
            ip_address="127.0.0.1",
        )
        self.assertEqual(cancelled.status, Order.Status.CANCELLED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="ORDER_CANCELLED",
                target_id=str(cancelled.pk),
            ).exists()
        )
        with self.assertRaises(OrderAlreadyClosedError):
            set_order_item(
                order_id=order.pk,
                drink_id=self.negroni.pk,
                quantity=1,
            )

    def test_close_and_pay_locks_ingredients_in_ascending_id_order(self):
        order = create_order(table_number=10, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.negroni.pk,
            quantity=1,
        )

        with CaptureQueriesContext(connection) as query_ctx:
            close_and_pay_order(order_id=order.pk, actor=self.bartender_one)

        ingredient_queries = [
            query["sql"]
            for query in query_ctx.captured_queries
            if '"bar_baringredient"' in query["sql"]
            and "ORDER BY" in query["sql"]
        ]
        self.assertTrue(
            any(
                '"bar_baringredient"."id" ASC' in sql_query
                for sql_query in ingredient_queries
            )
        )


class ModularViewsAndEndpointsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = Bartender.objects.create_user(
            username="view_owner",
            password="test_password123",
            staff_id="VIEW_OWN1",
            role=Bartender.Role.OWNER,
        )
        self.manager = Bartender.objects.create_user(
            username="view_manager",
            password="test_password123",
            staff_id="VIEW_MGR1",
            role=Bartender.Role.MANAGER,
        )
        self.bartender_one = Bartender.objects.create_user(
            username="view_bar1",
            password="test_password123",
            staff_id="VIEW_BAR1",
            role=Bartender.Role.BARTENDER,
        )
        self.bartender_two = Bartender.objects.create_user(
            username="view_bar2",
            password="test_password123",
            staff_id="VIEW_BAR2",
            role=Bartender.Role.BARTENDER,
        )
        self.supplier = BarSupplier.objects.create(
            name="View Spirits Supply",
            phone="+380501112299",
        )
        self.category = DrinksCategory.objects.create(name="View Cocktails")
        self.gin = BarIngredient.objects.create(
            name="View Gin",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("100.00"),
            cost_per_unit=Decimal("1.5000"),
            min_stock_threshold=Decimal("50.00"),
            supplier=self.supplier,
        )
        self.tonic = BarIngredient.objects.create(
            name="View Tonic",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("20.00"),
            cost_per_unit=Decimal("0.5000"),
            min_stock_threshold=Decimal("50.00"),
            supplier=self.supplier,
        )
        self.gin_tonic = Drink.objects.create(
            name="View Gin Tonic",
            price=Decimal("250.00"),
            volume_ml=200,
            target_food_cost_pct=Decimal("25.00"),
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=self.gin_tonic,
            ingredient=self.gin,
            amount=Decimal("50.00"),
        )
        DrinkIngredient.objects.create(
            drink=self.gin_tonic,
            ingredient=self.tonic,
            amount=Decimal("100.00"),
        )
        self.straight_gin = Drink.objects.create(
            name="=EvilDrink",
            price=Decimal("200.00"),
            volume_ml=50,
            target_food_cost_pct=Decimal("25.00"),
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=self.straight_gin,
            ingredient=self.gin,
            amount=Decimal("50.00"),
        )

    def tearDown(self):
        cache.clear()

    def test_drink_costing_preview_and_drink_views_context(self):
        self.client.force_login(self.bartender_one)
        forbidden = self.client.get(reverse("bar:drink-costing-preview"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.manager)
        preview_response = self.client.post(
            reverse("bar:drink-costing-preview"),
            data={
                "price": "300.00",
                "target_food_cost_pct": "25.00",
                "recipe_items-TOTAL_FORMS": "1",
                "recipe_items-0-ingredient": str(self.gin.pk),
                "recipe_items-0-amount": "50.00",
            },
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(
            preview_response.context["costing"].cost_price,
            Decimal("75.00"),
        )
        self.assertEqual(
            preview_response.context["costing"].gross_margin,
            Decimal("225.00"),
        )
        self.assertIsNone(preview_response.context["preview_error"])

        invalid_response = self.client.post(
            reverse("bar:drink-costing-preview"),
            data={"price": "not-a-number"},
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIsNotNone(invalid_response.context["preview_error"])

        list_response = self.client.get(reverse("bar:drink-list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(self.gin_tonic.pk, list_response.context["costing_map"])

        detail_response = self.client.get(
            reverse("bar:drink-detail", args=[self.gin_tonic.pk])
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.context["costing"].cost_price,
            Decimal("125.00"),
        )

    def test_inventory_hub_views_and_rbac(self):
        self.client.force_login(self.bartender_one)
        for route_name in (
            "bar:stock-movement-list",
            "bar:stock-in",
            "bar:stock-writeoff",
            "bar:stock-adjustment",
        ):
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 403)

        self.client.force_login(self.manager)
        stock_in_resp = self.client.post(
            reverse("bar:stock-in"),
            data={
                "ingredient": self.gin.pk,
                "quantity": "100.00",
                "unit_cost": "2.5000",
                "reason": "Bar delivery",
            },
        )
        self.assertEqual(stock_in_resp.status_code, 302)
        self.gin.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("200.00"))
        self.assertEqual(self.gin.cost_per_unit, Decimal("2.0000"))

        bad_writeoff = self.client.post(
            reverse("bar:stock-writeoff"),
            data={
                "ingredient": self.gin.pk,
                "quantity": "999.00",
                "reason": "Spilled bottle",
            },
        )
        self.assertEqual(bad_writeoff.status_code, 400)

        good_writeoff = self.client.post(
            reverse("bar:stock-writeoff"),
            data={
                "ingredient": self.gin.pk,
                "quantity": "20.00",
                "reason": "Broken bottle",
            },
        )
        self.assertEqual(good_writeoff.status_code, 302)
        self.gin.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("180.00"))

        adjust_resp = self.client.post(
            reverse("bar:stock-adjustment"),
            data={
                "ingredient": self.gin.pk,
                "actual_quantity": "175.00",
                "reason": "Shift inventory count",
            },
        )
        self.assertEqual(adjust_resp.status_code, 302)
        self.gin.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("175.00"))

        movements_resp = self.client.get(
            reverse("bar:stock-movement-list"),
            {"movement_type": StockMovement.MovementType.IN},
        )
        self.assertEqual(movements_resp.status_code, 200)
        self.assertEqual(len(movements_resp.context["movement_list"]), 1)

    def test_order_pos_endpoints_stop_list_and_force_close(self):
        self.client.force_login(self.bartender_one)
        create_resp = self.client.post(
            reverse("bar:order-create"),
            data={"table_number": 12, "assign_to_me": "on"},
        )
        self.assertEqual(create_resp.status_code, 302)
        order = Order.objects.get(table_number=12)
        self.assertEqual(order.bartender, self.bartender_one)

        add_resp = self.client.post(
            reverse("bar:order-add-item", args=[order.pk]),
            data={"drink_id": self.straight_gin.pk, "delta": 1},
        )
        self.assertEqual(add_resp.status_code, 302)

        set_resp = self.client.post(
            reverse(
                "bar:order-set-item",
                args=[order.pk, self.straight_gin.pk],
            ),
            data={"quantity": 2},
        )
        self.assertEqual(set_resp.status_code, 302)
        self.assertEqual(
            OrderItem.objects.get(
                order=order,
                drink=self.straight_gin,
            ).quantity,
            2,
        )

        remove_resp = self.client.post(
            reverse(
                "bar:order-remove-item",
                args=[order.pk, self.straight_gin.pk],
            )
        )
        self.assertEqual(remove_resp.status_code, 302)
        self.assertFalse(
            OrderItem.objects.filter(
                order=order,
                drink=self.straight_gin,
            ).exists()
        )

        self.client.post(
            reverse("bar:order-add-item", args=[order.pk]),
            data={"drink_id": self.straight_gin.pk, "delta": 1},
        )
        self.client.force_login(self.bartender_two)
        other_pay_resp = self.client.post(
            reverse("bar:order-pay", args=[order.pk])
        )
        self.assertEqual(other_pay_resp.status_code, 403)

        self.client.force_login(self.bartender_one)
        pay_ok = self.client.post(reverse("bar:order-pay", args=[order.pk]))
        self.assertEqual(pay_ok.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.gin.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("50.00"))

        shortage_order = create_order(
            table_number=15,
            bartender=self.bartender_one,
        )
        set_order_item(
            order_id=shortage_order.pk,
            drink_id=self.gin_tonic.pk,
            quantity=1,
        )
        deficit_resp = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk])
        )
        self.assertEqual(deficit_resp.status_code, 409)
        self.assertEqual(len(deficit_resp.context["deficits"]), 1)
        self.tonic.refresh_from_db()
        self.assertEqual(self.tonic.stock_quantity, Decimal("20.00"))

        bartender_force = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk]),
            data={"force_override": "1", "override_reason": "Trying override"},
        )
        self.assertEqual(bartender_force.status_code, 403)

        self.client.force_login(self.manager)
        invalid_force = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk]),
            data={"force_override": "1", "override_reason": "x"},
        )
        self.assertEqual(invalid_force.status_code, 400)

        valid_force = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk]),
            data={
                "force_override": "1",
                "override_reason": "VIP reserve bottle poured",
            },
        )
        self.assertEqual(valid_force.status_code, 302)
        shortage_order.refresh_from_db()
        self.assertEqual(shortage_order.status, Order.Status.PAID)
        self.tonic.refresh_from_db()
        self.assertEqual(self.tonic.stock_quantity, Decimal("0.00"))
        self.assertTrue(
            AuditLog.objects.filter(
                action="FORCE_CLOSE_ORDER",
                target_id=str(shortage_order.pk),
            ).exists()
        )

        cancel_target = create_order(
            table_number=21,
            bartender=self.bartender_one,
        )
        self.client.force_login(self.bartender_one)
        cancel_resp = self.client.post(
            reverse("bar:order-cancel", args=[cancel_target.pk]),
            data={"reason": "Guest left"},
        )
        self.assertEqual(cancel_resp.status_code, 302)
        cancel_target.refresh_from_db()
        self.assertEqual(cancel_target.status, Order.Status.CANCELLED)

        order_list_resp = self.client.get(
            reverse("bar:order-list"),
            {"status": Order.Status.PAID, "mine": "1"},
        )
        self.assertEqual(order_list_resp.status_code, 200)
        listed_orders = list(order_list_resp.context["order_list"])
        self.assertEqual(len(listed_orders), 2)
        self.assertGreater(listed_orders[0].calculated_total, Decimal("0.00"))

    def test_analytics_audit_staff_detail_and_login_redirect(self):
        order = create_order(table_number=8, bartender=self.bartender_one)
        set_order_item(
            order_id=order.pk,
            drink_id=self.straight_gin.pk,
            quantity=1,
        )
        close_and_pay_order(order_id=order.pk, actor=self.bartender_one)

        self.client.force_login(self.bartender_one)
        login_redirect = self.client.get(reverse("login"))
        self.assertEqual(login_redirect.status_code, 302)

        for route_name in (
            "bar:analytics",
            "bar:analytics-export",
            "bar:audit-list",
        ):
            self.assertEqual(
                self.client.get(reverse(route_name)).status_code,
                403,
            )

        self.client.force_login(self.manager)
        analytics_resp = self.client.get(
            reverse("bar:analytics"),
            {"period": "today"},
        )
        self.assertEqual(analytics_resp.status_code, 200)
        self.assertEqual(
            analytics_resp.context["report"].revenue,
            Decimal("200.00"),
        )

        csv_resp = self.client.get(
            reverse("bar:analytics-export"),
            {"period": "today"},
        )
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp["Content-Type"])
        self.assertIn("attachment;", csv_resp["Content-Disposition"])
        self.assertIn("'=EvilDrink", csv_resp.content.decode("utf-8"))

        AuditLog.objects.create(
            actor=self.owner,
            action="MANUAL_CHECK",
            target_model="Order",
            target_id=str(order.pk),
        )
        audit_resp = self.client.get(
            reverse("bar:audit-list"),
            {"action": "MANUAL_CHECK", "actor": self.owner.pk},
        )
        self.assertEqual(audit_resp.status_code, 200)
        self.assertEqual(len(audit_resp.context["audit_logs"]), 1)

        staff_detail = self.client.get(
            reverse("bar:bartender-detail", args=[self.bartender_one.pk])
        )
        self.assertEqual(staff_detail.status_code, 200)
        staff_obj = staff_detail.context["object"]
        self.assertEqual(staff_obj.paid_orders_count, 1)
        self.assertEqual(staff_obj.total_revenue, Decimal("200.00"))

    def test_order_idor_and_inactive_drink_blocked(self):
        order = create_order(
            table_number=19,
            bartender=self.bartender_one,
        )
        add_order_item(
            order_id=order.pk,
            drink_id=self.straight_gin.pk,
            delta=1,
            actor=self.bartender_one,
        )
        initial_status = order.status

        self.client.force_login(self.bartender_two)
        detail_resp = self.client.get(
            reverse("bar:order-detail", args=[order.pk])
        )
        self.assertEqual(detail_resp.status_code, 200)
        self.assertFalse(detail_resp.context["can_modify_items"])
        self.assertFalse(detail_resp.context["can_pay_order"])
        add_url = reverse("bar:order-add-item", args=[order.pk])
        cancel_url = reverse("bar:order-cancel", args=[order.pk])
        self.assertNotContains(detail_resp, add_url)
        self.assertNotContains(detail_resp, cancel_url)

        for_add = self.client.post(
            add_url,
            data={"drink_id": self.straight_gin.pk, "delta": 1},
        )
        self.assertEqual(for_add.status_code, 403)
        for_set = self.client.post(
            reverse(
                "bar:order-set-item",
                args=[order.pk, self.straight_gin.pk],
            ),
            data={"quantity": 3},
        )
        self.assertEqual(for_set.status_code, 403)
        for_remove = self.client.post(
            reverse(
                "bar:order-remove-item",
                args=[order.pk, self.straight_gin.pk],
            )
        )
        self.assertEqual(for_remove.status_code, 403)
        for_cancel = self.client.post(cancel_url)
        self.assertEqual(for_cancel.status_code, 403)

        order_item = OrderItem.objects.get(
            order=order, drink=self.straight_gin
        )
        self.assertEqual(order_item.quantity, 1)
        order.refresh_from_db()
        self.assertEqual(order.status, initial_status)

        inactive_drink = Drink.objects.create(
            name="Stopped Negroni",
            price=Decimal("220.00"),
            volume_ml=120,
            target_food_cost_pct=Decimal("25.00"),
            category=self.category,
            is_active=False,
        )
        with self.assertRaises(OrderStateError):
            add_order_item(
                order_id=order.pk,
                drink_id=inactive_drink.pk,
                delta=1,
                actor=self.bartender_one,
            )

        self.client.force_login(self.bartender_one)
        htmx_inactive = self.client.post(
            add_url,
            data={"drink_id": inactive_drink.pk, "delta": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(htmx_inactive.status_code, 200)
        trigger_payload = json.loads(htmx_inactive["HX-Trigger"])
        self.assertEqual(trigger_payload["showToast"]["level"], "error")
        self.assertFalse(
            OrderItem.objects.filter(
                order=order, drink=inactive_drink
            ).exists()
        )
