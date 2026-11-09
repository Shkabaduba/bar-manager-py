from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import BartenderCreationForm, BartenderStaffUpdateForm
from .models import BarSupplier, Drink, DrinksCategory, Order


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
