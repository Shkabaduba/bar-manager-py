from decimal import Decimal
import io
from pathlib import Path
import tempfile

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
import polib

from bar.admin import (
    AuditLogAdmin,
    DrinkAdmin,
    OrderAdmin,
    StockMovementAdmin,
)
from bar.forms import (
    BarIngredientCreateForm,
    BarIngredientUpdateForm,
    BartenderCreationForm,
    BartenderStaffUpdateForm,
    DrinkIngredientFormSet,
    DrinkRecipeForm,
    IngredientSearchForm,
    OrderCreateForm,
    OrderForceCloseForm,
    StaffCreateForm,
    StockAdjustmentForm,
    StockInForm,
    StockWriteoffForm,
    SupplierSearchForm,
)
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
from bar.services.costing import (
    AvailabilityStatus,
    FoodCostZone,
    RecipeLineInput,
    calculate_drink_costing,
    calculate_drink_unit_cost,
    calculate_drinks_costing_map,
    calculate_recipe_costing,
)


class ModelTest(TestCase):
    def test_supplier_str(self):
        barsupplier = BarSupplier.objects.create(
            name="PepsiCo",
            phone="Test phone number",
        )
        self.assertEqual(
            str(barsupplier),
            f"{barsupplier.name} ({barsupplier.phone})",
        )

    def test_bartender_str(self):
        bartender = get_user_model().objects.create(
            username="test_bartender",
            first_name="Vasil",
            last_name="Bondar",
        )
        self.assertEqual(
            str(bartender),
            f"{bartender.username}"
            f" ({bartender.first_name} {bartender.last_name})",
        )

    def test_drink_str(self):
        category = DrinksCategory.objects.create(name="Cocktails")
        drink = Drink.objects.create(
            name="Mojito",
            price=12.50,
            volume_ml=300,
            category=category,
        )
        self.assertEqual(
            str(drink),
            f"{drink.name} ({drink.volume_ml}ml - ${drink.price})",
        )

    def test_create_bartender_with_staff_id(self):
        username = "test_bartender"
        password = "test_password123"
        staff_id = "Test staff id"
        bartender = get_user_model().objects.create_user(
            username=username,
            password=password,
            staff_id=staff_id,
        )
        self.assertEqual(bartender.username, username)
        self.assertEqual(bartender.staff_id, staff_id)
        self.assertTrue(bartender.check_password(password))


class FormTest(TestCase):
    def test_bartender_create_form(self):
        form_data = {
            "username": "test_bartender",
            "first_name": "Vasil",
            "last_name": "Bondar",
            "staff_id": "ABC12345",
            "password1": "TestPass12345!",
            "password2": "TestPass12345!",
        }
        form = BartenderCreationForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data, form_data)

    def test_staff_id_validation(self):
        invalid_staff_id = [
            "ABC",
            "ABC12345623434*?:",
            "ab(;)",
            "12C12345впукуцацу",
            "A;",
        ]
        for staff_id in invalid_staff_id:
            form = BartenderStaffUpdateForm(
                data={"staff_id": staff_id}
            )
            self.assertFalse(form.is_valid())

    def test_supplier_search_form(self):
        form = SupplierSearchForm(data={"name": "Metro"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["name"], "Metro")

    def test_ingredient_search_form(self):
        form = IngredientSearchForm(data={"name": "Mint"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["name"], "Mint")


class ModelConstraintsAndRolesTests(TestCase):
    def test_bartender_role_helpers(self):
        owner = Bartender.objects.create_user(
            username="owner_user",
            password="test_password123",
            staff_id="OWNER_001",
            role=Bartender.Role.OWNER,
        )
        manager = Bartender.objects.create_user(
            username="manager_user",
            password="test_password123",
            staff_id="MANAGER01",
            role=Bartender.Role.MANAGER,
        )
        bartender = Bartender.objects.create_user(
            username="bartender_user",
            password="test_password123",
            staff_id="BARTEND01",
            role=Bartender.Role.BARTENDER,
        )
        superuser = Bartender.objects.create_superuser(
            username="super_user",
            password="test_password123",
            staff_id="SUPER_001",
        )

        self.assertTrue(owner.is_owner)
        self.assertFalse(owner.is_manager)
        self.assertFalse(owner.is_bartender)
        self.assertTrue(owner.can_manage_bar)
        self.assertTrue(owner.can_force_close)
        self.assertTrue(owner.can_manage_staff)
        self.assertTrue(owner.can_view_analytics)

        self.assertFalse(manager.is_owner)
        self.assertTrue(manager.is_manager)
        self.assertFalse(manager.is_bartender)
        self.assertTrue(manager.can_manage_bar)
        self.assertTrue(manager.can_force_close)
        self.assertFalse(manager.can_manage_staff)
        self.assertTrue(manager.can_view_analytics)

        self.assertFalse(bartender.is_owner)
        self.assertFalse(bartender.is_manager)
        self.assertTrue(bartender.is_bartender)
        self.assertFalse(bartender.can_manage_bar)
        self.assertFalse(bartender.can_force_close)
        self.assertFalse(bartender.can_manage_staff)
        self.assertFalse(bartender.can_view_analytics)

        self.assertTrue(superuser.is_owner)
        self.assertFalse(superuser.is_bartender)
        self.assertTrue(superuser.can_manage_staff)

    def test_staff_id_and_phone_model_validators(self):
        valid_supplier = BarSupplier(
            name="Valid Spirits",
            phone="+380501112233",
        )
        valid_supplier.full_clean()

        invalid_supplier = BarSupplier(name="Bad Phone", phone="abc")
        with self.assertRaises(ValidationError):
            invalid_supplier.full_clean()

        valid_bartender = Bartender(
            username="valid_staff",
            password="test_password123",
            staff_id="STAFF_01",
        )
        valid_bartender.full_clean()

        for bad_staff_id in ("abc", "bad;id!123", "12C12345вася"):
            invalid_bartender = Bartender(
                username="bad_staff",
                password="test_password123",
                staff_id=bad_staff_id,
            )
            with self.assertRaises(ValidationError) as ctx:
                invalid_bartender.full_clean()
            self.assertIn("staff_id", ctx.exception.message_dict)

    def test_protect_on_delete_blocks_referenced_records(self):
        supplier = BarSupplier.objects.create(
            name="Protect Supplier",
            phone="+380501112233",
        )
        ingredient = BarIngredient.objects.create(
            name="Protect Rum",
            stock_quantity=Decimal("100.00"),
            supplier=supplier,
        )
        category = DrinksCategory.objects.create(name="Protect Cocktails")
        drink = Drink.objects.create(
            name="Protect Daiquiri",
            price=Decimal("150.00"),
            volume_ml=120,
            category=category,
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=ingredient,
            amount=Decimal("50.00"),
        )
        order = Order.objects.create(table_number=7)
        OrderItem.objects.create(
            order=order,
            drink=drink,
            quantity=1,
            unit_price_snapshot=drink.price,
        )

        with self.assertRaises(ProtectedError):
            supplier.delete()
        with self.assertRaises(ProtectedError):
            category.delete()
        with self.assertRaises(ProtectedError):
            ingredient.delete()
        with self.assertRaises(ProtectedError):
            drink.delete()

    def test_db_check_constraints_enforce_invariants(self):
        supplier = BarSupplier.objects.create(
            name="Constraint Supplier",
            phone="+380501112244",
        )
        category = DrinksCategory.objects.create(name="Constraint Category")
        ingredient = BarIngredient.objects.create(
            name="Constraint Gin",
            stock_quantity=Decimal("50.00"),
            supplier=supplier,
        )
        drink = Drink.objects.create(
            name="Constraint Tonic",
            price=Decimal("120.00"),
            volume_ml=200,
            category=category,
        )
        order = Order.objects.create(table_number=3)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BarIngredient.objects.create(
                    name="Neg Stock",
                    stock_quantity=Decimal("-1.00"),
                    supplier=supplier,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BarIngredient.objects.create(
                    name="Neg Cost",
                    cost_per_unit=Decimal("-0.5000"),
                    supplier=supplier,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Drink.objects.create(
                    name="Zero Price Drink",
                    price=Decimal("0.00"),
                    volume_ml=100,
                    category=category,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DrinkIngredient.objects.create(
                    drink=drink,
                    ingredient=ingredient,
                    amount=Decimal("0.00"),
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrderItem.objects.create(
                    order=order,
                    drink=drink,
                    quantity=0,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    ingredient=ingredient,
                    movement_type=StockMovement.MovementType.ADJUSTMENT,
                    quantity_delta=Decimal("-60.00"),
                    balance_after=Decimal("-1.00"),
                )

        AuditLog.objects.create(
            action="CHECK_TEST",
            target_model="Order",
            target_id=str(order.pk),
        )
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_unique_constraints_on_through_models(self):
        supplier = BarSupplier.objects.create(
            name="Unique Supplier",
            phone="+380501112255",
        )
        category = DrinksCategory.objects.create(name="Unique Category")
        ingredient = BarIngredient.objects.create(
            name="Unique Vodka",
            stock_quantity=Decimal("100.00"),
            supplier=supplier,
        )
        drink = Drink.objects.create(
            name="Unique Martini",
            price=Decimal("200.00"),
            volume_ml=100,
            category=category,
        )
        order = Order.objects.create(table_number=4)

        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=ingredient,
            amount=Decimal("50.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DrinkIngredient.objects.create(
                    drink=drink,
                    ingredient=ingredient,
                    amount=Decimal("25.00"),
                )

        OrderItem.objects.create(
            order=order,
            drink=drink,
            quantity=1,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrderItem.objects.create(
                    order=order,
                    drink=drink,
                    quantity=2,
                )

    def test_create_drink_view_populates_drink_ingredient_through_model(self):
        user = get_user_model().objects.create_user(
            username="recipe_tester",
            password="test_password123",
            staff_id="RECIPE_01",
            role=Bartender.Role.MANAGER,
        )
        self.client.force_login(user)
        category = DrinksCategory.objects.create(name="Recipe Cocktails")
        supplier = BarSupplier.objects.create(
            name="Recipe Supplier",
            phone="+380501112266",
        )
        ingredient = BarIngredient.objects.create(
            name="Recipe Rum",
            stock_quantity=Decimal("500.00"),
            supplier=supplier,
        )
        response = self.client.post(
            reverse("bar:drink-create"),
            data={
                "name": "Cuba Libre",
                "price": "180.00",
                "volume_ml": 250,
                "target_food_cost_pct": "25.00",
                "is_active": True,
                "category": category.id,
                "recipe_items-TOTAL_FORMS": "1",
                "recipe_items-INITIAL_FORMS": "0",
                "recipe_items-MIN_NUM_FORMS": "0",
                "recipe_items-MAX_NUM_FORMS": "1000",
                "recipe_items-0-ingredient": str(ingredient.id),
                "recipe_items-0-amount": "50.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        drink = Drink.objects.get(name="Cuba Libre")
        recipe_item = DrinkIngredient.objects.get(
            drink=drink,
            ingredient=ingredient,
        )
        self.assertEqual(recipe_item.amount, Decimal("50.00"))


class CostingServiceTests(TestCase):
    def setUp(self):
        self.supplier = BarSupplier.objects.create(
            name="Costing Supplier",
            phone="+380501112200",
        )
        self.category = DrinksCategory.objects.create(name="Costing Cocktails")

    def _create_ingredient(
        self,
        name: str,
        stock: str,
        cost: str,
        unit: str = BarIngredient.Unit.ML,
    ) -> BarIngredient:
        return BarIngredient.objects.create(
            name=name,
            unit=unit,
            stock_quantity=Decimal(stock),
            cost_per_unit=Decimal(cost),
            supplier=self.supplier,
        )

    def test_costing_basic_cocktail_metrics(self):
        gin = self._create_ingredient("Costing Gin", "1000.00", "1.0000")
        vermouth = self._create_ingredient(
            "Costing Vermouth",
            "1000.00",
            "0.5000",
        )
        campari = self._create_ingredient(
            "Costing Campari",
            "1000.00",
            "0.5000",
        )
        orange_peel = self._create_ingredient(
            "Orange Slice",
            "50.00",
            "20.0000",
            unit=BarIngredient.Unit.PCS,
        )
        drink = Drink.objects.create(
            name="Costing Negroni",
            price=Decimal("400.00"),
            volume_ml=90,
            target_food_cost_pct=Decimal("25.00"),
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=gin,
            amount=Decimal("30.00"),
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=vermouth,
            amount=Decimal("30.00"),
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=campari,
            amount=Decimal("30.00"),
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=orange_peel,
            amount=Decimal("1.00"),
        )

        costing = calculate_drink_costing(drink)
        self.assertEqual(costing.cost_price, Decimal("80.00"))
        self.assertEqual(costing.gross_margin, Decimal("320.00"))
        self.assertEqual(costing.food_cost_pct, Decimal("20.00"))
        self.assertEqual(costing.food_cost_zone, FoodCostZone.OPTIMAL)
        self.assertEqual(costing.markup_pct, Decimal("400.00"))
        self.assertEqual(costing.recommended_price, Decimal("320.00"))
        self.assertEqual(costing.estimated_volume_ml, 90)
        self.assertEqual(costing.max_portions, 33)
        self.assertEqual(
            costing.availability_status,
            AvailabilityStatus.AVAILABLE,
        )

        shares = {
            line.ingredient_name: line.cost_share_pct
            for line in costing.lines
        }
        self.assertEqual(shares["Costing Gin"], Decimal("37.50"))
        self.assertEqual(shares["Costing Vermouth"], Decimal("18.75"))
        self.assertEqual(shares["Costing Campari"], Decimal("18.75"))
        self.assertEqual(shares["Orange Slice"], Decimal("25.00"))

    def test_food_cost_zones_boundaries(self):
        spirit = self._create_ingredient("Boundary Spirit", "500.00", "1.0000")
        lines = [RecipeLineInput(ingredient=spirit, amount=Decimal("25.00"))]

        optimal_edge = calculate_recipe_costing(lines, price=Decimal("100.00"))
        self.assertEqual(optimal_edge.food_cost_pct, Decimal("25.00"))
        self.assertEqual(optimal_edge.food_cost_zone, FoodCostZone.OPTIMAL)

        moderate_low = calculate_recipe_costing(lines, price=Decimal("99.95"))
        self.assertEqual(moderate_low.food_cost_pct, Decimal("25.01"))
        self.assertEqual(moderate_low.food_cost_zone, FoodCostZone.MODERATE)

        moderate_edge_lines = [
            RecipeLineInput(ingredient=spirit, amount=Decimal("35.00"))
        ]
        moderate_high = calculate_recipe_costing(
            moderate_edge_lines,
            price=Decimal("100.00"),
        )
        self.assertEqual(moderate_high.food_cost_pct, Decimal("35.00"))
        self.assertEqual(moderate_high.food_cost_zone, FoodCostZone.MODERATE)

        high_zone = calculate_recipe_costing(
            moderate_edge_lines,
            price=Decimal("99.96"),
        )
        self.assertEqual(high_zone.food_cost_pct, Decimal("35.01"))
        self.assertEqual(high_zone.food_cost_zone, FoodCostZone.HIGH)

    def test_availability_status_and_limiting_ingredient(self):
        plenty = self._create_ingredient("Plenty Rum", "500.00", "1.0000")
        low_syrup = self._create_ingredient("Low Syrup", "150.00", "0.2000")

        low_costing = calculate_recipe_costing(
            [
                RecipeLineInput(ingredient=plenty, amount=Decimal("50.00")),
                RecipeLineInput(ingredient=low_syrup, amount=Decimal("30.00")),
            ],
            price=Decimal("250.00"),
        )
        self.assertEqual(low_costing.max_portions, 5)
        self.assertEqual(
            low_costing.availability_status,
            AvailabilityStatus.LOW_STOCK,
        )
        lines_by_name = {
            line.ingredient_name: line for line in low_costing.lines
        }
        self.assertFalse(lines_by_name["Plenty Rum"].is_limiting)
        self.assertTrue(lines_by_name["Low Syrup"].is_limiting)
        self.assertFalse(lines_by_name["Low Syrup"].is_out_of_stock)

        fractional_short = self._create_ingredient(
            "Short Lime",
            "29.99",
            "0.3000",
        )
        stop_costing = calculate_recipe_costing(
            [
                RecipeLineInput(ingredient=plenty, amount=Decimal("50.00")),
                RecipeLineInput(
                    ingredient=fractional_short,
                    amount=Decimal("30.00"),
                ),
            ],
            price=Decimal("250.00"),
        )
        self.assertEqual(stop_costing.max_portions, 0)
        self.assertEqual(
            stop_costing.availability_status,
            AvailabilityStatus.STOP_LIST,
        )
        stop_lines = {
            line.ingredient_name: line for line in stop_costing.lines
        }
        self.assertTrue(stop_lines["Short Lime"].is_out_of_stock)
        self.assertTrue(stop_lines["Short Lime"].is_limiting)

        available_costing = calculate_recipe_costing(
            [RecipeLineInput(ingredient=plenty, amount=Decimal("50.00"))],
            price=Decimal("250.00"),
        )
        self.assertEqual(available_costing.max_portions, 10)
        self.assertEqual(
            available_costing.availability_status,
            AvailabilityStatus.AVAILABLE,
        )

    def test_empty_recipe_and_zero_cost_edge_cases(self):
        costing = calculate_recipe_costing([], price=Decimal("150.00"))
        self.assertEqual(costing.cost_price, Decimal("0.00"))
        self.assertEqual(costing.gross_margin, Decimal("150.00"))
        self.assertEqual(costing.food_cost_pct, Decimal("0.00"))
        self.assertEqual(costing.food_cost_zone, FoodCostZone.OPTIMAL)
        self.assertIsNone(costing.markup_pct)
        self.assertEqual(costing.recommended_price, Decimal("0.00"))
        self.assertEqual(costing.estimated_volume_ml, 0)
        self.assertIsNone(costing.max_portions)
        self.assertEqual(
            costing.availability_status,
            AvailabilityStatus.AVAILABLE,
        )
        self.assertEqual(costing.lines, ())

    def test_zero_price_live_preview_edge_case(self):
        vodka = self._create_ingredient("Zero Price Vodka", "300.00", "1.0000")
        costing = calculate_recipe_costing(
            [RecipeLineInput(ingredient=vodka, amount=Decimal("50.00"))],
            price=Decimal("0.00"),
            target_food_cost_pct=Decimal("25.00"),
        )
        self.assertEqual(costing.cost_price, Decimal("50.00"))
        self.assertEqual(costing.gross_margin, Decimal("-50.00"))
        self.assertEqual(costing.food_cost_pct, Decimal("0.00"))
        self.assertEqual(costing.recommended_price, Decimal("200.00"))

    def test_live_simulator_aggregates_duplicate_ingredients(self):
        whiskey = self._create_ingredient("Duplicate Bourbon", "90.00", "2.00")
        costing = calculate_recipe_costing(
            [
                RecipeLineInput(ingredient=whiskey, amount=Decimal("30.00")),
                RecipeLineInput(ingredient=whiskey, amount=Decimal("20.00")),
            ],
            price=Decimal("400.00"),
        )
        self.assertEqual(len(costing.lines), 1)
        self.assertEqual(costing.lines[0].amount, Decimal("50.00"))
        self.assertEqual(costing.lines[0].available_portions, 1)
        self.assertEqual(costing.max_portions, 1)
        self.assertEqual(costing.cost_price, Decimal("100.00"))

    def test_validation_rejects_invalid_inputs(self):
        spirit = self._create_ingredient("Validated Spirit", "100.00", "1.00")
        valid_lines = [
            RecipeLineInput(ingredient=spirit, amount=Decimal("10"))
        ]

        with self.assertRaises(ValueError):
            calculate_recipe_costing(valid_lines, price=Decimal("-1.00"))
        with self.assertRaises(ValueError):
            calculate_recipe_costing(
                valid_lines,
                price=Decimal("100.00"),
                target_food_cost_pct=Decimal("0.00"),
            )
        with self.assertRaises(ValueError):
            calculate_recipe_costing(
                valid_lines,
                price=Decimal("100.00"),
                target_food_cost_pct=Decimal("100.01"),
            )
        with self.assertRaises(ValueError):
            calculate_recipe_costing(
                [RecipeLineInput(ingredient=spirit, amount=Decimal("0.00"))],
                price=Decimal("100.00"),
            )

    def test_calculate_drink_costing_zero_extra_queries_with_prefetch(self):
        ingredients = [
            self._create_ingredient(f"Prefetch Ing {index}", "500.00", "1.00")
            for index in range(3)
        ]
        for index in range(5):
            drink = Drink.objects.create(
                name=f"Prefetch Drink {index}",
                price=Decimal("300.00"),
                volume_ml=150,
                category=self.category,
            )
            for ingredient in ingredients:
                DrinkIngredient.objects.create(
                    drink=drink,
                    ingredient=ingredient,
                    amount=Decimal("40.00"),
                )

        prefetched_drinks = list(
            Drink.objects.filter(category=self.category).prefetch_related(
                "recipe_items__ingredient"
            )
        )
        with self.assertNumQueries(0):
            costing_map = calculate_drinks_costing_map(prefetched_drinks)
        self.assertEqual(len(costing_map), 5)

    def test_calculate_drink_unit_cost_four_decimal_precision(self):
        precision_ing = self._create_ingredient(
            "Precision Bitter",
            "300.00",
            "0.3333",
        )
        drink = Drink.objects.create(
            name="Precision Cocktail",
            price=Decimal("200.00"),
            volume_ml=30,
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=precision_ing,
            amount=Decimal("30.00"),
        )
        self.assertEqual(
            calculate_drink_unit_cost(drink),
            Decimal("9.9990"),
        )
        costing = calculate_drink_costing(drink)
        self.assertEqual(costing.cost_price, Decimal("10.00"))


class FormsAdminAndCommandsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.supplier = BarSupplier.objects.create(
            name="Form Supplier",
            phone="+380501112244",
        )
        self.category = DrinksCategory.objects.create(name="Form Cocktails")
        self.ingredient = BarIngredient.objects.create(
            name="Form Gin",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("200.00"),
            cost_per_unit=Decimal("1.0000"),
            supplier=self.supplier,
        )

    def tearDown(self):
        cache.clear()

    def test_drink_ingredient_formset_rejects_duplicate_and_zero_amount(self):
        drink_form = DrinkRecipeForm(
            data={
                "name": "Form Negroni",
                "category": self.category.pk,
                "price": "300.00",
                "volume_ml": 90,
                "target_food_cost_pct": "25.00",
                "is_active": True,
                "description": "Test",
            }
        )
        self.assertTrue(drink_form.is_valid())
        drink = drink_form.save()

        dup_formset = DrinkIngredientFormSet(
            instance=drink,
            data={
                "recipe_items-TOTAL_FORMS": "2",
                "recipe_items-INITIAL_FORMS": "0",
                "recipe_items-MIN_NUM_FORMS": "0",
                "recipe_items-MAX_NUM_FORMS": "1000",
                "recipe_items-0-ingredient": str(self.ingredient.pk),
                "recipe_items-0-amount": "30.00",
                "recipe_items-1-ingredient": str(self.ingredient.pk),
                "recipe_items-1-amount": "20.00",
            },
        )
        self.assertFalse(dup_formset.is_valid())
        self.assertIn("only once", " ".join(dup_formset.non_form_errors()))

        zero_formset = DrinkIngredientFormSet(
            instance=drink,
            data={
                "recipe_items-TOTAL_FORMS": "1",
                "recipe_items-INITIAL_FORMS": "0",
                "recipe_items-MIN_NUM_FORMS": "0",
                "recipe_items-MAX_NUM_FORMS": "1000",
                "recipe_items-0-ingredient": str(self.ingredient.pk),
                "recipe_items-0-amount": "0.00",
            },
        )
        self.assertFalse(zero_formset.is_valid())
        self.assertIn("amount", zero_formset.forms[0].errors)

        valid_formset = DrinkIngredientFormSet(
            instance=drink,
            data={
                "recipe_items-TOTAL_FORMS": "1",
                "recipe_items-INITIAL_FORMS": "0",
                "recipe_items-MIN_NUM_FORMS": "0",
                "recipe_items-MAX_NUM_FORMS": "1000",
                "recipe_items-0-ingredient": str(self.ingredient.pk),
                "recipe_items-0-amount": "45.00",
            },
        )
        self.assertTrue(valid_formset.is_valid())
        valid_formset.save()
        self.assertEqual(drink.recipe_items.count(), 1)

    def test_inventory_forms_validate_and_exclude_direct_stock_edit(self):
        self.assertNotIn("stock_quantity", BarIngredientCreateForm.Meta.fields)
        self.assertNotIn("stock_quantity", BarIngredientUpdateForm.Meta.fields)
        self.assertNotIn("cost_per_unit", BarIngredientUpdateForm.Meta.fields)

        update_form = BarIngredientUpdateForm(
            instance=self.ingredient,
            data={
                "name": "Updated Gin",
                "unit": BarIngredient.Unit.ML,
                "min_stock_threshold": "-5.00",
                "supplier": self.supplier.pk,
            },
        )
        self.assertFalse(update_form.is_valid())
        self.assertIn("min_stock_threshold", update_form.errors)

        stock_in = StockInForm(
            data={
                "ingredient": self.ingredient.pk,
                "quantity": "100.00",
                "unit_cost": "1.2000",
                "reason": "Delivery",
            }
        )
        self.assertTrue(stock_in.is_valid())

        bad_writeoff = StockWriteoffForm(
            data={
                "ingredient": self.ingredient.pk,
                "quantity": "10.00",
                "reason": "   ",
            }
        )
        self.assertFalse(bad_writeoff.is_valid())
        self.assertIn("reason", bad_writeoff.errors)

        bad_adjustment = StockAdjustmentForm(
            data={
                "ingredient": self.ingredient.pk,
                "actual_quantity": "-1.00",
                "reason": "Audit",
            }
        )
        self.assertFalse(bad_adjustment.is_valid())
        self.assertIn("actual_quantity", bad_adjustment.errors)

    def test_order_create_and_force_close_forms_validation(self):
        create_form = OrderCreateForm(
            data={"table_number": 0, "assign_to_me": True}
        )
        self.assertFalse(create_form.is_valid())

        valid_create = OrderCreateForm(
            data={"table_number": 7, "assign_to_me": False}
        )
        self.assertTrue(valid_create.is_valid())

        bad_force = OrderForceCloseForm(data={"override_reason": "  ok "})
        self.assertFalse(bad_force.is_valid())
        self.assertIn("override_reason", bad_force.errors)

        good_force = OrderForceCloseForm(
            data={
                "override_reason": "VIP bottle reserve",
                "expected_version": 2,
            }
        )
        self.assertTrue(good_force.is_valid())

    def test_staff_create_form_includes_role_and_preserves_legacy(self):
        self.assertNotIn("role", BartenderCreationForm.Meta.fields)
        self.assertIn("role", StaffCreateForm.Meta.fields)
        form = StaffCreateForm(
            data={
                "username": "new_manager_1",
                "staff_id": "MGR_NEW01",
                "first_name": "Nina",
                "last_name": "Bar",
                "role": Bartender.Role.MANAGER,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            }
        )
        self.assertTrue(form.is_valid())
        created = form.save()
        self.assertEqual(created.role, Bartender.Role.MANAGER)

    def test_admin_inlines_and_readonly_ledgers(self):
        factory = RequestFactory()
        request = factory.get("/admin/")
        request.user = Bartender.objects.create_superuser(
            username="admin_tester",
            password="test_password123",
            staff_id="ADM_TEST1",
        )
        self.assertIn(Drink, admin.site._registry)
        self.assertIsInstance(admin.site._registry[Drink], DrinkAdmin)
        self.assertIsInstance(admin.site._registry[Order], OrderAdmin)

        movement_admin = StockMovementAdmin(StockMovement, admin.site)
        audit_admin = AuditLogAdmin(AuditLog, admin.site)
        for ledger_admin in (movement_admin, audit_admin):
            self.assertFalse(ledger_admin.has_add_permission(request))
            self.assertFalse(ledger_admin.has_change_permission(request))
            self.assertFalse(ledger_admin.has_delete_permission(request))

    def test_compile_locales_command_compiles_po_to_mo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lc_dir = Path(temp_dir) / "uk" / "LC_MESSAGES"
            lc_dir.mkdir(parents=True)
            po_path = lc_dir / "django.po"
            po_path.write_text(
                'msgid ""\n'
                'msgstr ""\n'
                '"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
                'msgid "Dashboard"\n'
                'msgstr "Панель керування"\n',
                encoding="utf-8",
            )
            output = io.StringIO()
            with override_settings(LOCALE_PATHS=[Path(temp_dir)]):
                call_command("compile_locales", stdout=output)

            mo_path = lc_dir / "django.mo"
            self.assertTrue(mo_path.exists())
            compiled = polib.mofile(str(mo_path))
            self.assertEqual(compiled[0].msgstr, "Панель керування")
            self.assertIn("Compiled 1 locale file(s).", output.getvalue())

    def test_seed_demo_data_command_is_idempotent(self):
        output_first = io.StringIO()
        call_command("seed_demo_data", stdout=output_first)

        self.assertEqual(Bartender.objects.count(), 3)
        self.assertEqual(BarSupplier.objects.count(), 4)
        self.assertEqual(DrinksCategory.objects.count(), 4)
        self.assertEqual(BarIngredient.objects.count(), 9)
        self.assertEqual(Drink.objects.count(), 3)
        self.assertEqual(StockMovement.objects.count(), 8)

        gin = BarIngredient.objects.get(name="London Dry Gin")
        self.assertEqual(gin.stock_quantity, Decimal("2000.00"))
        owner = Bartender.objects.get(username="owner")
        self.assertTrue(owner.groups.filter(name="Owners").exists())

        output_second = io.StringIO()
        call_command("seed_demo_data", stdout=output_second)

        self.assertEqual(Bartender.objects.count(), 3)
        self.assertEqual(BarSupplier.objects.count(), 4)
        self.assertEqual(BarIngredient.objects.count(), 9)
        self.assertEqual(Drink.objects.count(), 3)
        self.assertEqual(StockMovement.objects.count(), 8)
        gin.refresh_from_db()
        self.assertEqual(gin.stock_quantity, Decimal("2000.00"))
