from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction

from bar.middleware import parse_ip_address
from bar.models import AuditLog, BarIngredient, Bartender, StockMovement
from bar.services.cache import schedule_analytics_cache_invalidation
from bar.services.exceptions import (
    InsufficientStockError,
    InvalidQuantityError,
    StockDeficit,
)

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def _to_decimal(raw_value: Decimal | str | int) -> Decimal:
    try:
        return Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidQuantityError("Invalid numeric value.") from exc


def _quantize(amount: Decimal, places: Decimal) -> Decimal:
    return amount.quantize(places, rounding=ROUND_HALF_UP)


def _require_reason(reason: str) -> str:
    clean_reason = reason.strip()
    if not clean_reason:
        raise InvalidQuantityError("Reason is required for this operation.")
    return clean_reason


def record_stock_in(
    *,
    ingredient_id: int,
    quantity: Decimal,
    unit_cost: Decimal,
    performed_by: Bartender | None = None,
    reason: str = "",
    ip_address: str | None = None,
) -> StockMovement:
    """Receive stock and recalculate weighted average ingredient cost."""
    in_quantity = _quantize(_to_decimal(quantity), TWO_PLACES)
    in_unit_cost = _quantize(_to_decimal(unit_cost), FOUR_PLACES)
    if in_quantity <= ZERO:
        raise InvalidQuantityError(
            "Stock receipt quantity must be greater than zero."
        )
    if in_unit_cost < ZERO:
        raise InvalidQuantityError("Unit cost cannot be negative.")

    with transaction.atomic():
        ingredient = BarIngredient.objects.select_for_update().get(
            pk=ingredient_id
        )
        old_quantity = ingredient.stock_quantity
        old_cost = ingredient.cost_per_unit
        new_quantity = _quantize(old_quantity + in_quantity, TWO_PLACES)
        new_cost = _quantize(
            (old_quantity * old_cost + in_quantity * in_unit_cost)
            / new_quantity,
            FOUR_PLACES,
        )
        total_cost = _quantize(in_quantity * in_unit_cost, TWO_PLACES)

        ingredient.stock_quantity = new_quantity
        ingredient.cost_per_unit = new_cost
        ingredient.save(update_fields=["stock_quantity", "cost_per_unit"])

        movement = StockMovement.objects.create(
            ingredient=ingredient,
            movement_type=StockMovement.MovementType.IN,
            quantity_delta=in_quantity,
            balance_after=new_quantity,
            unit_cost=in_unit_cost,
            total_cost=total_cost,
            reason=reason.strip(),
            performed_by=performed_by,
        )
        schedule_analytics_cache_invalidation()
    return movement


def record_writeoff(
    *,
    ingredient_id: int,
    quantity: Decimal,
    reason: str,
    performed_by: Bartender | None = None,
    ip_address: str | None = None,
) -> StockMovement:
    """Deduct spoiled or broken stock and record StockMovement + AuditLog."""
    writeoff_quantity = _quantize(_to_decimal(quantity), TWO_PLACES)
    if writeoff_quantity <= ZERO:
        raise InvalidQuantityError(
            "Write-off quantity must be greater than zero."
        )
    clean_reason = _require_reason(reason)

    with transaction.atomic():
        ingredient = BarIngredient.objects.select_for_update().get(
            pk=ingredient_id
        )
        if ingredient.stock_quantity < writeoff_quantity:
            deficit = StockDeficit(
                ingredient_id=ingredient.pk,
                ingredient_name=ingredient.name,
                unit=ingredient.unit,
                required=writeoff_quantity,
                available=ingredient.stock_quantity,
                shortfall=_quantize(
                    writeoff_quantity - ingredient.stock_quantity,
                    TWO_PLACES,
                ),
            )
            raise InsufficientStockError([deficit])

        new_quantity = _quantize(
            ingredient.stock_quantity - writeoff_quantity,
            TWO_PLACES,
        )
        unit_cost = ingredient.cost_per_unit
        total_cost = _quantize(writeoff_quantity * unit_cost, TWO_PLACES)

        ingredient.stock_quantity = new_quantity
        ingredient.save(update_fields=["stock_quantity"])

        movement = StockMovement.objects.create(
            ingredient=ingredient,
            movement_type=StockMovement.MovementType.WRITEOFF,
            quantity_delta=-writeoff_quantity,
            balance_after=new_quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            reason=clean_reason,
            performed_by=performed_by,
        )
        AuditLog.objects.create(
            actor=performed_by,
            action="STOCK_WRITEOFF",
            target_model="BarIngredient",
            target_id=str(ingredient.pk),
            metadata={
                "ingredient_name": ingredient.name,
                "quantity": str(writeoff_quantity),
                "unit": ingredient.unit,
                "balance_after": str(new_quantity),
                "total_cost": str(total_cost),
                "reason": clean_reason,
            },
            ip_address=parse_ip_address(ip_address) if ip_address else None,
        )
        schedule_analytics_cache_invalidation()
    return movement


def record_adjustment(
    *,
    ingredient_id: int,
    actual_quantity: Decimal,
    reason: str,
    performed_by: Bartender | None = None,
    ip_address: str | None = None,
) -> StockMovement:
    """Reconcile counted stock balance and log delta in ledger + audit."""
    actual_qty = _quantize(_to_decimal(actual_quantity), TWO_PLACES)
    if actual_qty < ZERO:
        raise InvalidQuantityError("Actual stock quantity cannot be negative.")
    clean_reason = _require_reason(reason)

    with transaction.atomic():
        ingredient = BarIngredient.objects.select_for_update().get(
            pk=ingredient_id
        )
        previous_quantity = ingredient.stock_quantity
        quantity_delta = _quantize(actual_qty - previous_quantity, TWO_PLACES)
        unit_cost = ingredient.cost_per_unit
        total_cost = _quantize(abs(quantity_delta) * unit_cost, TWO_PLACES)

        if quantity_delta != ZERO:
            ingredient.stock_quantity = actual_qty
            ingredient.save(update_fields=["stock_quantity"])

        movement = StockMovement.objects.create(
            ingredient=ingredient,
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            quantity_delta=quantity_delta,
            balance_after=actual_qty,
            unit_cost=unit_cost,
            total_cost=total_cost,
            reason=clean_reason,
            performed_by=performed_by,
        )
        AuditLog.objects.create(
            actor=performed_by,
            action="STOCK_ADJUSTMENT",
            target_model="BarIngredient",
            target_id=str(ingredient.pk),
            metadata={
                "ingredient_name": ingredient.name,
                "previous_quantity": str(previous_quantity),
                "actual_quantity": str(actual_qty),
                "delta": str(quantity_delta),
                "unit": ingredient.unit,
                "total_cost": str(total_cost),
                "reason": clean_reason,
            },
            ip_address=parse_ip_address(ip_address) if ip_address else None,
        )
        schedule_analytics_cache_invalidation()
    return movement
