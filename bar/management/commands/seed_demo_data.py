from decimal import Decimal

from django.core.management.base import BaseCommand

from bar.models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinkIngredient,
    DrinksCategory,
)
from bar.permissions import sync_bartender_group
from bar.services.inventory import record_stock_in

DEMO_USERS = (
    {
        "username": "owner",
        "staff_id": "OWNER_DEMO",
        "role": Bartender.Role.OWNER,
        "first_name": "Elena",
        "last_name": "Vlasenko",
        "is_staff": True,
        "password": "OwnerPass123!",
    },
    {
        "username": "manager",
        "staff_id": "MANAGER_01",
        "role": Bartender.Role.MANAGER,
        "first_name": "Maksym",
        "last_name": "Koval",
        "is_staff": True,
        "password": "ManagerPass123!",
    },
    {
        "username": "user",
        "staff_id": "BARTENDER_01",
        "role": Bartender.Role.BARTENDER,
        "first_name": "Taras",
        "last_name": "Melnyk",
        "is_staff": False,
        "password": "user12345",
    },
)

DEMO_SUPPLIERS = (
    {
        "name": "AlcoTrade",
        "phone": "+380501112233",
        "email": "orders@alcotrade.example",
        "notes": "Primary spirits distributor",
    },
    {
        "name": "GinBittersAlco",
        "phone": "+380502223344",
        "email": "supply@ginbitters.example",
        "notes": "Vermouths, aperitifs, and bitters",
    },
    {
        "name": "FreshCraftSyrups",
        "phone": "+380503334455",
        "email": "hello@freshcraft.example",
        "notes": "Citrus, herbs, and craft syrups",
    },
)

DEMO_CATEGORIES = (
    {"name": "Signature Cocktails", "is_alcohol": True},
    {"name": "Classic Cocktails", "is_alcohol": True},
    {"name": "Non-Alcoholic", "is_alcohol": False},
)

DEMO_INGREDIENTS = (
    {
        "name": "London Dry Gin",
        "unit": BarIngredient.Unit.ML,
        "min_threshold": Decimal("500.00"),
        "supplier": "GinBittersAlco",
        "initial_stock": Decimal("2000.00"),
        "unit_cost": Decimal("0.9000"),
    },
    {
        "name": "Sweet Vermouth",
        "unit": BarIngredient.Unit.ML,
        "min_threshold": Decimal("400.00"),
        "supplier": "GinBittersAlco",
        "initial_stock": Decimal("1500.00"),
        "unit_cost": Decimal("0.6000"),
    },
    {
        "name": "Campari",
        "unit": BarIngredient.Unit.ML,
        "min_threshold": Decimal("400.00"),
        "supplier": "GinBittersAlco",
        "initial_stock": Decimal("1500.00"),
        "unit_cost": Decimal("0.7000"),
    },
    {
        "name": "Bourbon Whiskey",
        "unit": BarIngredient.Unit.ML,
        "min_threshold": Decimal("500.00"),
        "supplier": "AlcoTrade",
        "initial_stock": Decimal("2000.00"),
        "unit_cost": Decimal("1.1000"),
    },
    {
        "name": "Fresh Lemon Juice",
        "unit": BarIngredient.Unit.ML,
        "min_threshold": Decimal("300.00"),
        "supplier": "FreshCraftSyrups",
        "initial_stock": Decimal("1200.00"),
        "unit_cost": Decimal("0.2500"),
    },
    {
        "name": "Sugar Syrup",
        "unit": BarIngredient.Unit.ML,
        "min_threshold": Decimal("300.00"),
        "supplier": "FreshCraftSyrups",
        "initial_stock": Decimal("1500.00"),
        "unit_cost": Decimal("0.1500"),
    },
    {
        "name": "Fresh Mint",
        "unit": BarIngredient.Unit.GRAMS,
        "min_threshold": Decimal("50.00"),
        "supplier": "FreshCraftSyrups",
        "initial_stock": Decimal("300.00"),
        "unit_cost": Decimal("0.4000"),
    },
    {
        "name": "Orange Slice",
        "unit": BarIngredient.Unit.PCS,
        "min_threshold": Decimal("10.00"),
        "supplier": "FreshCraftSyrups",
        "initial_stock": Decimal("40.00"),
        "unit_cost": Decimal("5.0000"),
    },
)

DEMO_DRINKS = (
    {
        "name": "Classic Negroni",
        "category": "Classic Cocktails",
        "price": Decimal("360.00"),
        "volume_ml": 90,
        "target_food_cost_pct": Decimal("25.00"),
        "description": "Balanced bitter aperitif served over clear ice.",
        "recipe": (
            ("London Dry Gin", Decimal("30.00")),
            ("Sweet Vermouth", Decimal("30.00")),
            ("Campari", Decimal("30.00")),
            ("Orange Slice", Decimal("1.00")),
        ),
    },
    {
        "name": "Whiskey Sour",
        "category": "Signature Cocktails",
        "price": Decimal("340.00"),
        "volume_ml": 100,
        "target_food_cost_pct": Decimal("25.00"),
        "description": "Bourbon shaken with fresh lemon juice and syrup.",
        "recipe": (
            ("Bourbon Whiskey", Decimal("50.00")),
            ("Fresh Lemon Juice", Decimal("30.00")),
            ("Sugar Syrup", Decimal("20.00")),
        ),
    },
    {
        "name": "Virgin Mint Lemonade",
        "category": "Non-Alcoholic",
        "price": Decimal("140.00"),
        "volume_ml": 250,
        "target_food_cost_pct": Decimal("20.00"),
        "description": "Refreshing non-alcoholic citrus cooler.",
        "recipe": (
            ("Fresh Lemon Juice", Decimal("40.00")),
            ("Sugar Syrup", Decimal("30.00")),
            ("Fresh Mint", Decimal("10.00")),
        ),
    },
)


class Command(BaseCommand):
    help = (  # noqa: VNE003
        "Idempotently seed demo roles, suppliers, stock, and cocktails."
    )

    def handle(self, *args, **options):
        users_by_name: dict[str, Bartender] = {}
        for spec in DEMO_USERS:
            bartender, created = Bartender.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "staff_id": spec["staff_id"],
                    "role": spec["role"],
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                    "is_staff": spec["is_staff"],
                },
            )
            if created:
                bartender.set_password(spec["password"])
                bartender.save(update_fields=["password"])
            sync_bartender_group(bartender)
            users_by_name[spec["username"]] = bartender

        owner = users_by_name["owner"]

        suppliers = {
            spec["name"]: BarSupplier.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "phone": spec["phone"],
                    "email": spec["email"],
                    "notes": spec["notes"],
                },
            )[0]
            for spec in DEMO_SUPPLIERS
        }

        categories = {
            spec["name"]: DrinksCategory.objects.get_or_create(
                name=spec["name"],
                defaults={"is_alcohol": spec["is_alcohol"]},
            )[0]
            for spec in DEMO_CATEGORIES
        }

        ingredients: dict[str, BarIngredient] = {}
        for spec in DEMO_INGREDIENTS:
            ingredient, _ = BarIngredient.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "unit": spec["unit"],
                    "min_stock_threshold": spec["min_threshold"],
                    "supplier": suppliers[spec["supplier"]],
                },
            )
            if not ingredient.movements.exists():
                record_stock_in(
                    ingredient_id=ingredient.pk,
                    quantity=spec["initial_stock"],
                    unit_cost=spec["unit_cost"],
                    performed_by=owner,
                    reason="Demo seed initial stock",
                )
                ingredient.refresh_from_db()
            ingredients[spec["name"]] = ingredient

        for spec in DEMO_DRINKS:
            drink, _ = Drink.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "category": categories[spec["category"]],
                    "price": spec["price"],
                    "volume_ml": spec["volume_ml"],
                    "target_food_cost_pct": spec["target_food_cost_pct"],
                    "description": spec["description"],
                },
            )
            for ingredient_name, amount in spec["recipe"]:
                DrinkIngredient.objects.get_or_create(
                    drink=drink,
                    ingredient=ingredients[ingredient_name],
                    defaults={"amount": amount},
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(users_by_name)} roles, "
                f"{len(ingredients)} ingredients, and "
                f"{len(DEMO_DRINKS)} drinks."
            )
        )
