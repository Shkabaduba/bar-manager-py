from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bar", "0004_migrate_existing_data"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="drink",
            name="ingredients",
        ),
        migrations.AddField(
            model_name="drink",
            name="ingredients",
            field=models.ManyToManyField(
                related_name="drinks",
                through="bar.DrinkIngredient",
                to="bar.baringredient",
            ),
        ),
        migrations.RemoveField(
            model_name="order",
            name="drinks",
        ),
        migrations.AddField(
            model_name="order",
            name="drinks",
            field=models.ManyToManyField(
                related_name="orders",
                through="bar.OrderItem",
                to="bar.drink",
            ),
        ),
        migrations.AddConstraint(
            model_name="baringredient",
            constraint=models.CheckConstraint(
                condition=models.Q(("stock_quantity__gte", 0)),
                name="ingredient_stock_quantity_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="baringredient",
            constraint=models.CheckConstraint(
                condition=models.Q(("cost_per_unit__gte", 0)),
                name="ingredient_cost_per_unit_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="baringredient",
            constraint=models.CheckConstraint(
                condition=models.Q(("min_stock_threshold__gte", 0)),
                name="ingredient_min_stock_gte_0",
            ),
        ),
        migrations.AddIndex(
            model_name="baringredient",
            index=models.Index(
                fields=["stock_quantity"],
                name="bar_ing_stock_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="baringredient",
            index=models.Index(
                fields=["supplier", "name"],
                name="bar_ing_supplier_name_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="drink",
            constraint=models.CheckConstraint(
                condition=models.Q(("price__gt", 0)),
                name="drink_price_gt_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="drink",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("target_food_cost_pct__gt", 0),
                    ("target_food_cost_pct__lte", 100),
                ),
                name="drink_target_food_cost_range",
            ),
        ),
        migrations.AddIndex(
            model_name="drink",
            index=models.Index(
                fields=["is_active", "name"],
                name="bar_drink_active_name_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="drinkingredient",
            constraint=models.UniqueConstraint(
                fields=("drink", "ingredient"),
                name="unique_drink_ingredient",
            ),
        ),
        migrations.AddConstraint(
            model_name="drinkingredient",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0)),
                name="drink_ingredient_amount_gt_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="order_version_gte_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("total_revenue_snapshot__gte", 0)),
                name="order_revenue_snapshot_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("total_cost_snapshot__gte", 0)),
                name="order_cost_snapshot_gte_0",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["status", "-created_at"],
                name="bar_order_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["bartender", "status"],
                name="bar_order_bartender_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["-paid_at"],
                name="bar_order_paid_at_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.UniqueConstraint(
                fields=("order", "drink"),
                name="unique_order_drink",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gte", 1)),
                name="order_item_quantity_gte_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_price_snapshot__gte", 0)),
                name="order_item_price_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_cost_snapshot__gte", 0)),
                name="order_item_cost_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                condition=models.Q(("balance_after__gte", 0)),
                name="stock_movement_balance_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_cost__gte", 0)),
                name="stock_movement_unit_cost_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                condition=models.Q(("shortfall_quantity__gte", 0)),
                name="stock_movement_shortfall_gte_0",
            ),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(
                fields=["ingredient", "-created_at"],
                name="bar_sm_ing_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(
                fields=["movement_type", "-created_at"],
                name="bar_sm_type_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["action", "-created_at"],
                name="bar_audit_action_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["actor", "-created_at"],
                name="bar_audit_actor_created_idx",
            ),
        ),
    ]
