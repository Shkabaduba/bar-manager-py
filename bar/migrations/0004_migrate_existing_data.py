from decimal import Decimal

from django.db import migrations


def migrate_data_forward(apps, schema_editor):
    bartender_model = apps.get_model("bar", "Bartender")
    bar_ingredient_model = apps.get_model("bar", "BarIngredient")
    drink_model = apps.get_model("bar", "Drink")
    drink_ingredient_model = apps.get_model("bar", "DrinkIngredient")
    order_model = apps.get_model("bar", "Order")
    order_item_model = apps.get_model("bar", "OrderItem")
    stock_movement_model = apps.get_model("bar", "StockMovement")

    for bartender in bartender_model.objects.all():
        if bartender.is_superuser:
            bartender.role = "OWNER"
        elif bartender.is_staff:
            bartender.role = "MANAGER"
        else:
            bartender.role = "BARTENDER"

        if not (bartender.staff_id or "").strip():
            prefix = "OWNER" if bartender.is_superuser else "STAFF"
            bartender.staff_id = f"{prefix}_{bartender.pk:04d}"

        bartender.save(update_fields=["role", "staff_id"])

    drink_through = drink_model.ingredients.through
    for row in drink_through.objects.all():
        drink_ingredient_model.objects.get_or_create(
            drink_id=row.drink_id,
            ingredient_id=row.baringredient_id,
            defaults={"amount": Decimal("50.00")},
        )

    drink_prices = dict(drink_model.objects.values_list("id", "price"))
    order_through = order_model.drinks.through
    for row in order_through.objects.all():
        order_item_model.objects.get_or_create(
            order_id=row.order_id,
            drink_id=row.drink_id,
            defaults={
                "quantity": 1,
                "unit_price_snapshot": drink_prices.get(
                    row.drink_id, Decimal("0.00")
                ),
                "unit_cost_snapshot": Decimal("0.0000"),
            },
        )

    for order in order_model.objects.all():
        if order.is_paid:
            order.status = "PAID"
            order.paid_at = order.created_at
            total_revenue = sum(
                (
                    item.unit_price_snapshot * item.quantity
                    for item in order_item_model.objects.filter(
                        order_id=order.pk
                    )
                ),
                Decimal("0.00"),
            )
            order.total_revenue_snapshot = total_revenue
        elif order.bartender_id:
            order.status = "IN_PROGRESS"
        else:
            order.status = "OPEN"
        order.save(
            update_fields=["status", "paid_at", "total_revenue_snapshot"]
        )

    for ingredient in bar_ingredient_model.objects.filter(stock_quantity__gt=0):
        if not stock_movement_model.objects.filter(
            ingredient_id=ingredient.pk
        ).exists():
            stock_movement_model.objects.create(
                ingredient_id=ingredient.pk,
                movement_type="ADJUSTMENT",
                quantity_delta=ingredient.stock_quantity,
                balance_after=ingredient.stock_quantity,
                unit_cost=ingredient.cost_per_unit,
                total_cost=Decimal("0.00"),
                reason="Initial stock migration",
            )


def migrate_data_backward(apps, schema_editor):
    drink_model = apps.get_model("bar", "Drink")
    drink_ingredient_model = apps.get_model("bar", "DrinkIngredient")
    order_model = apps.get_model("bar", "Order")
    order_item_model = apps.get_model("bar", "OrderItem")
    stock_movement_model = apps.get_model("bar", "StockMovement")

    drink_through = drink_model.ingredients.through
    for item in drink_ingredient_model.objects.all():
        drink_through.objects.get_or_create(
            drink_id=item.drink_id,
            baringredient_id=item.ingredient_id,
        )

    order_through = order_model.drinks.through
    for item in order_item_model.objects.all():
        order_through.objects.get_or_create(
            order_id=item.order_id,
            drink_id=item.drink_id,
        )

    stock_movement_model.objects.filter(
        reason="Initial stock migration"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("bar", "0003_expand_schema"),
    ]

    operations = [
        migrations.RunPython(migrate_data_forward, migrate_data_backward),
    ]
