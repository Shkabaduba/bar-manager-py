from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import (
    BartenderCreationForm,
    BartenderStaffUpdateForm,
    SupplierSearchForm,
    IngredientSearchForm,
)
from .models import BarSupplier, Drink, DrinksCategory, Order, BarIngredient


class ModelTest(TestCase):
    def test_supplier_str(self):
        barsupplier = BarSupplier.objects.create(
            name="PepsiCo",
            phone="Test phone number",
        )
        self.assertEqual(
            str(barsupplier),
            f"{barsupplier.name} ({barsupplier.phone})"
        )

    def test_bartender_str(self):
        bartender = get_user_model().objects.create(
            username="test_bartender",
            first_name="Vasil",
            last_name="Bondar"
        )
        self.assertEqual(
            str(bartender),
            f"{bartender.username}"
            f" ({bartender.first_name} {bartender.last_name})"
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
            f"{drink.name} ({drink.volume_ml}ml - ${drink.price})"
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


class PublicViewTests(TestCase):
    def test_login_required(self):
        urls = [
            reverse("bar:index"),
            reverse("bar:bartender-list"),
            reverse("bar:drink-list"),
            reverse("bar:category-list"),
            reverse("bar:order-list"),
            reverse("bar:supplier-list"),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertNotEqual(response.status_code, 200)


class PrivateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test_driver",
            password="test_password123",
            staff_id="Acf",
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
            "category": category.id,
            "ingredients": [ingredient.id],
        }
        response = self.client.post(
            reverse("bar:drink-create"),
            data=form_data
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
            "category": category.id,
            "ingredients": [ingredient.id],
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
            is_alcohol=True
        )
        cat2 = DrinksCategory.objects.create(
            name="Lemonades",
            is_alcohol=False
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
        for url in urls:
            response = self.client.get(url)
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
            "stock_quantity": 4,
            "supplier": supplier.id,
        }
        response = self.client.post(
            reverse("bar:ingredient-create"), data=data
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            BarIngredient.objects.filter(name="Angostura Bitters").exists()
        )

    def test_update_ingredient(self):
        supplier = BarSupplier.objects.create(
            name="Distributor Y", phone="+380504445577"
        )
        ingredient = BarIngredient.objects.create(
            name="Vodka", stock_quantity=8, supplier=supplier
        )
        data = {
            "name": "Premium Vodka",
            "stock_quantity": 12,
            "supplier": supplier.id,
        }
        response = self.client.post(
            reverse("bar:ingredient-update", args=[ingredient.id]), data=data
        )
        self.assertEqual(response.status_code, 302)
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.name, "Premium Vodka")
        self.assertEqual(ingredient.stock_quantity, 12)

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
