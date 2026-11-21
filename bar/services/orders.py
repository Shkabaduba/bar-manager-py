from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from bar.middleware import parse_ip_address
from bar.models import (
    AuditLog,
    BarIngredient,
    Bartender,
    Drink,
    Order,
    OrderItem,
    StockMovement,
)
from bar.services.cache import schedule_analytics_cache_invalidation
from bar.services.costing import calculate_drink_unit_cost
from bar.services.exceptions import (
    InsufficientStockError,
    InvalidQuantityError,
    OptimisticLockError,
    OrderAlreadyClosedError,
    OrderStateError,
    StockDeficit,
)

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
FINAL_ORDER_STATUSES = frozenset({
    Order.Status.PAID,
    Order.Status.CANCELLED,
})


def _quantize(amount: Decimal, places: Decimal) -> Decimal:
    return amount.quantize(places, rounding=ROUND_HALF_UP)


def _lock_mutable_order(
    order_id: int,
    expected_version: int | None = None,
) -> Order:
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status in FINAL_ORDER_STATUSES or order.is_paid:
        raise OrderAlreadyClosedError(
            f"Order #{order.pk} is already {order.status.lower()}."
        )
    if expected_version is not None and order.version != expected_version:
        raise OptimisticLockError(
            f"Order #{order.pk} was updated by another user."
        )
    return order


def _upsert_or_delete_order_item(
    order: Order,
    drink_id: int,
    new_quantity: int,
) -> OrderItem | None:
    if new_quantity <= 0:
        deleted_count, _ = OrderItem.objects.filter(
            order=order,
            drink_id=drink_id,
        ).delete()
        if deleted_count > 0:
            order.version += 1
            order.save(update_fields=["version"])
            schedule_analytics_cache_invalidation()
        return None

    drink = Drink.objects.prefetch_related("recipe_items__ingredient").get(
        pk=drink_id
    )
    unit_cost = calculate_drink_unit_cost(drink)
    order_item, _ = OrderItem.objects.update_or_create(
        order=order,
        drink=drink,
        defaults={
            "quantity": new_quantity,
            "unit_price_snapshot": drink.price,
            "unit_cost_snapshot": unit_cost,
        },
    )
    order.version += 1
    order.save(update_fields=["version"])
    schedule_analytics_cache_invalidation()
    return order_item


def create_order(
    *,
    table_number: int,
    bartender: Bartender | None = None,
) -> Order:
    """Create a new OPEN or IN_PROGRESS order atomically."""
    if (
        isinstance(table_number, bool)
        or not isinstance(table_number, int)
        or table_number < 1
    ):
        raise InvalidQuantityError("Table number must be a positive integer.")

    with transaction.atomic():
        initial_status = (
            Order.Status.IN_PROGRESS if bartender else Order.Status.OPEN
        )
        order = Order.objects.create(
            table_number=table_number,
            bartender=bartender,
            status=initial_status,
            is_paid=False,
            version=1,
        )
        schedule_analytics_cache_invalidation()
    return order


def set_order_item(
    *,
    order_id: int,
    drink_id: int,
    quantity: int,
    expected_version: int | None = None,
) -> OrderItem | None:
    """Set exact quantity for a drink in an order, or delete if 0."""
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 0
    ):
        raise InvalidQuantityError("Quantity cannot be negative.")

    with transaction.atomic():
        order = _lock_mutable_order(
            order_id,
            expected_version=expected_version,
        )
        return _upsert_or_delete_order_item(order, drink_id, quantity)


def add_order_item(
    *,
    order_id: int,
    drink_id: int,
    delta: int = 1,
    expected_version: int | None = None,
) -> OrderItem | None:
    """Adjust drink quantity in an order by delta (delete when <= 0)."""
    if (
        isinstance(delta, bool)
        or not isinstance(delta, int)
        or delta == 0
    ):
        raise InvalidQuantityError("Quantity delta must be a non-zero int.")

    with transaction.atomic():
        order = _lock_mutable_order(
            order_id,
            expected_version=expected_version,
        )
        existing = OrderItem.objects.filter(
            order=order,
            drink_id=drink_id,
        ).first()
        current_quantity = existing.quantity if existing else 0
        return _upsert_or_delete_order_item(
            order,
            drink_id,
            current_quantity + delta,
        )


def remove_order_item(
    *,
    order_id: int,
    drink_id: int,
    expected_version: int | None = None,
) -> bool:
    """Remove a drink line from an order and bump version if removed."""
    with transaction.atomic():
        order = _lock_mutable_order(
            order_id,
            expected_version=expected_version,
        )
        deleted_count, _ = OrderItem.objects.filter(
            order=order,
            drink_id=drink_id,
        ).delete()
        if deleted_count > 0:
            order.version += 1
            order.save(update_fields=["version"])
            schedule_analytics_cache_invalidation()
            return True
    return False


def toggle_assign_order(
    *,
    order_id: int,
    actor: Bartender,
    expected_version: int | None = None,
) -> tuple[Order, str]:
    """Claim or release an unassigned/self-assigned order atomically."""
    with transaction.atomic():
        order = _lock_mutable_order(
            order_id,
            expected_version=expected_version,
        )
        if order.bartender_id == actor.pk:
            order.bartender = None
            order.status = Order.Status.OPEN
            order.version += 1
            order.save(update_fields=["bartender", "status", "version"])
            schedule_analytics_cache_invalidation()
            return order, "unassigned"
        if order.bartender_id is None:
            order.bartender = actor
            order.status = Order.Status.IN_PROGRESS
            order.version += 1
            order.save(update_fields=["bartender", "status", "version"])
            schedule_analytics_cache_invalidation()
            return order, "assigned"
        return order, "taken_by_other"


def cancel_order(
    *,
    order_id: int,
    actor: Bartender,
    reason: str = "",
    expected_version: int | None = None,
    ip_address: str | None = None,
) -> Order:
    """Cancel an unpaid order and record the event in AuditLog."""
    with transaction.atomic():
        order = _lock_mutable_order(
            order_id,
            expected_version=expected_version,
        )
        if not actor.can_manage_bar and order.bartender_id not in (
            None,
            actor.pk,
        ):
            raise PermissionDenied(
                "You can only cancel your own or unassigned orders."
            )
        clean_reason = reason.strip()
        order.status = Order.Status.CANCELLED
        order.closed_by = actor
        order.override_reason = clean_reason
        order.version += 1
        order.save(
            update_fields=["status", "closed_by", "override_reason", "version"]
        )
        AuditLog.objects.create(
            actor=actor,
            action="ORDER_CANCELLED",
            target_model="Order",
            target_id=str(order.pk),
            metadata={
                "table_number": order.table_number,
                "reason": clean_reason,
            },
            ip_address=parse_ip_address(ip_address) if ip_address else None,
        )
        schedule_analytics_cache_invalidation()
    return order


def _validate_pay_permissions(
    order: Order,
    actor: Bartender,
    force_override: bool,
    override_reason: str,
) -> str:
    if not actor.can_manage_bar and order.bartender_id != actor.pk:
        raise PermissionDenied(
            "Bartenders can only pay orders assigned to themselves."
        )
    clean_reason = override_reason.strip()
    if force_override:
        if not actor.can_force_close:
            raise PermissionDenied(
                "Only managers and owners can force-close orders "
                "with deficits."
            )
        if not clean_reason:
            raise InvalidQuantityError(
                "Override reason is required for force close."
            )
    return clean_reason


def _aggregate_order_requirements(
    order_items: list[OrderItem],
) -> dict[int, Decimal]:
    required_map: dict[int, Decimal] = {}
    for order_item in order_items:
        for recipe_item in order_item.drink.recipe_items.all():
            needed = _quantize(
                recipe_item.amount * order_item.quantity,
                TWO_PLACES,
            )
            ingredient_id = recipe_item.ingredient_id
            required_map[ingredient_id] = (
                required_map.get(ingredient_id, ZERO) + needed
            )
    return required_map


def _collect_stock_deficits(
    ingredient_ids: list[int],
    required_map: dict[int, Decimal],
    locked_map: dict[int, BarIngredient],
) -> list[StockDeficit]:
    deficits: list[StockDeficit] = []
    for ingredient_id in ingredient_ids:
        ingredient = locked_map[ingredient_id]
        required = required_map[ingredient_id]
        available = ingredient.stock_quantity
        if available < required:
            deficits.append(
                StockDeficit(
                    ingredient_id=ingredient.pk,
                    ingredient_name=ingredient.name,
                    unit=ingredient.unit,
                    required=required,
                    available=available,
                    shortfall=_quantize(required - available, TWO_PLACES),
                )
            )
    return deficits


def _snapshot_order_items(
    order_items: list[OrderItem],
    locked_map: dict[int, BarIngredient],
) -> tuple[Decimal, Decimal]:
    total_revenue = ZERO
    total_cost = ZERO
    for order_item in order_items:
        raw_unit_cost = sum(
            (
                recipe_item.amount
                * locked_map[recipe_item.ingredient_id].cost_per_unit
                for recipe_item in order_item.drink.recipe_items.all()
            ),
            ZERO,
        )
        order_item.unit_price_snapshot = order_item.drink.price
        order_item.unit_cost_snapshot = _quantize(raw_unit_cost, FOUR_PLACES)
        total_revenue += order_item.unit_price_snapshot * order_item.quantity
        total_cost += order_item.unit_cost_snapshot * order_item.quantity

    OrderItem.objects.bulk_update(
        order_items,
        ["unit_price_snapshot", "unit_cost_snapshot"],
    )
    return (
        _quantize(total_revenue, TWO_PLACES),
        _quantize(total_cost, TWO_PLACES),
    )


def _deduct_ingredients_and_create_movements(
    *,
    ingredient_ids: list[int],
    required_map: dict[int, Decimal],
    locked_map: dict[int, BarIngredient],
    order: Order,
    actor: Bartender,
    clean_reason: str,
) -> None:
    updated_ingredients: list[BarIngredient] = []
    movements: list[StockMovement] = []

    for ingredient_id in ingredient_ids:
        ingredient = locked_map[ingredient_id]
        required = required_map[ingredient_id]
        available = ingredient.stock_quantity
        deducted = min(available, required)
        shortfall = _quantize(required - deducted, TWO_PLACES)
        new_balance = _quantize(available - deducted, TWO_PLACES)

        ingredient.stock_quantity = new_balance
        updated_ingredients.append(ingredient)
        movements.append(
            StockMovement(
                ingredient=ingredient,
                movement_type=StockMovement.MovementType.OUT_ORDER,
                quantity_delta=-deducted,
                balance_after=new_balance,
                unit_cost=ingredient.cost_per_unit,
                total_cost=_quantize(
                    deducted * ingredient.cost_per_unit,
                    TWO_PLACES,
                ),
                shortfall_quantity=shortfall,
                reason=clean_reason if shortfall > ZERO else "",
                order=order,
                performed_by=actor,
            )
        )

    BarIngredient.objects.bulk_update(updated_ingredients, ["stock_quantity"])
    StockMovement.objects.bulk_create(movements)


def close_and_pay_order(
    *,
    order_id: int,
    actor: Bartender,
    force_override: bool = False,
    override_reason: str = "",
    expected_version: int | None = None,
    ip_address: str | None = None,
) -> Order:
    """Pay and close an order atomically with deadlock-free stock locking."""
    with transaction.atomic():
        order = _lock_mutable_order(
            order_id,
            expected_version=expected_version,
        )
        clean_reason = _validate_pay_permissions(
            order,
            actor,
            force_override,
            override_reason,
        )
        order_items = list(
            order.items.select_related("drink").prefetch_related(
                "drink__recipe_items"
            )
        )
        if not order_items:
            raise OrderStateError("Cannot pay an empty order.")

        required_map = _aggregate_order_requirements(order_items)
        ingredient_ids = sorted(required_map.keys())
        if ingredient_ids:
            locked_ingredients = list(
                BarIngredient.objects.select_for_update()
                .filter(pk__in=ingredient_ids)
                .order_by("id")
            )
            locked_map = {
                ingredient.pk: ingredient for ingredient in locked_ingredients
            }
        else:
            locked_map = {}

        deficits = _collect_stock_deficits(
            ingredient_ids,
            required_map,
            locked_map,
        )
        if deficits and not force_override:
            raise InsufficientStockError(deficits)

        total_revenue, total_cost = _snapshot_order_items(
            order_items,
            locked_map,
        )
        if ingredient_ids:
            _deduct_ingredients_and_create_movements(
                ingredient_ids=ingredient_ids,
                required_map=required_map,
                locked_map=locked_map,
                order=order,
                actor=actor,
                clean_reason=clean_reason,
            )

        order.status = Order.Status.PAID
        order.is_paid = True
        order.paid_at = timezone.now()
        order.closed_by = actor
        order.total_revenue_snapshot = total_revenue
        order.total_cost_snapshot = total_cost
        order.version += 1
        order_update_fields = [
            "status",
            "is_paid",
            "paid_at",
            "closed_by",
            "total_revenue_snapshot",
            "total_cost_snapshot",
            "version",
        ]

        if force_override and deficits:
            order.override_by = actor
            order.override_reason = clean_reason
            order_update_fields.extend(["override_by", "override_reason"])
            AuditLog.objects.create(
                actor=actor,
                action="FORCE_CLOSE_ORDER",
                target_model="Order",
                target_id=str(order.pk),
                metadata={
                    "table_number": order.table_number,
                    "reason": clean_reason,
                    "deficits": [
                        {
                            "ingredient_id": deficit.ingredient_id,
                            "ingredient_name": deficit.ingredient_name,
                            "unit": deficit.unit,
                            "required": str(deficit.required),
                            "available": str(deficit.available),
                            "shortfall": str(deficit.shortfall),
                        }
                        for deficit in deficits
                    ],
                },
                ip_address=(
                    parse_ip_address(ip_address) if ip_address else None
                ),
            )

        order.save(update_fields=order_update_fields)
        schedule_analytics_cache_invalidation()
    return order
