from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum

from bar.models import BarIngredient, Drink

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
OPTIMAL_FOOD_COST_MAX = Decimal("25.00")
MODERATE_FOOD_COST_MAX = Decimal("35.00")
LOW_STOCK_PORTIONS_THRESHOLD = 5


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    LOW_STOCK = "LOW_STOCK"
    STOP_LIST = "STOP_LIST"


class FoodCostZone(StrEnum):
    OPTIMAL = "OPTIMAL"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True)
class RecipeLineInput:
    """Ingredient and portion amount input for costing calculations."""

    ingredient: BarIngredient
    amount: Decimal


@dataclass(frozen=True)
class IngredientCostLine:
    """Computed cost, share, and stock capacity for one recipe ingredient."""

    ingredient_id: int
    ingredient_name: str
    unit: str
    amount: Decimal
    unit_cost: Decimal
    line_cost: Decimal
    cost_share_pct: Decimal
    stock_quantity: Decimal
    available_portions: int
    is_limiting: bool
    is_out_of_stock: bool


@dataclass(frozen=True)
class DrinkCosting:
    """Full financial and stock availability summary for a drink recipe."""

    price: Decimal
    target_food_cost_pct: Decimal
    cost_price: Decimal
    gross_margin: Decimal
    food_cost_pct: Decimal
    food_cost_zone: FoodCostZone
    markup_pct: Decimal | None
    recommended_price: Decimal
    estimated_volume_ml: int
    max_portions: int | None
    availability_status: AvailabilityStatus
    lines: tuple[IngredientCostLine, ...]


def _round_money(amount: Decimal) -> Decimal:
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _round_unit_cost(amount: Decimal) -> Decimal:
    return amount.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def _classify_food_cost(food_cost_pct: Decimal) -> FoodCostZone:
    if food_cost_pct <= OPTIMAL_FOOD_COST_MAX:
        return FoodCostZone.OPTIMAL
    if food_cost_pct <= MODERATE_FOOD_COST_MAX:
        return FoodCostZone.MODERATE
    return FoodCostZone.HIGH


def _classify_availability(max_portions: int | None) -> AvailabilityStatus:
    if max_portions is None:
        return AvailabilityStatus.AVAILABLE
    if max_portions == 0:
        return AvailabilityStatus.STOP_LIST
    if max_portions <= LOW_STOCK_PORTIONS_THRESHOLD:
        return AvailabilityStatus.LOW_STOCK
    return AvailabilityStatus.AVAILABLE


def _aggregate_lines(
    lines: Iterable[RecipeLineInput],
) -> list[RecipeLineInput]:
    merged: dict[int, RecipeLineInput] = {}
    for line in lines:
        amount = Decimal(line.amount)
        if amount <= ZERO:
            raise ValueError("Ingredient amount must be greater than zero.")
        key = (
            line.ingredient.pk
            if line.ingredient.pk is not None
            else id(line.ingredient)
        )
        if key in merged:
            existing = merged[key]
            merged[key] = RecipeLineInput(
                ingredient=existing.ingredient,
                amount=existing.amount + amount,
            )
        else:
            merged[key] = RecipeLineInput(
                ingredient=line.ingredient,
                amount=amount,
            )
    return list(merged.values())


def _build_cost_lines(
    aggregated_lines: list[RecipeLineInput],
) -> tuple[list[IngredientCostLine], Decimal, int | None]:
    raw_entries: list[tuple[RecipeLineInput, Decimal, int]] = []
    raw_total_cost = ZERO
    portion_counts: list[int] = []

    for line in aggregated_lines:
        raw_line_cost = line.amount * line.ingredient.cost_per_unit
        raw_total_cost += raw_line_cost
        available_portions = int(
            line.ingredient.stock_quantity // line.amount
        )
        portion_counts.append(available_portions)
        raw_entries.append((line, raw_line_cost, available_portions))

    max_portions = min(portion_counts) if portion_counts else None
    cost_lines: list[IngredientCostLine] = []

    for line, raw_line_cost, available_portions in raw_entries:
        cost_share_pct = (
            _round_money((raw_line_cost / raw_total_cost) * HUNDRED)
            if raw_total_cost > ZERO
            else Decimal("0.00")
        )
        cost_lines.append(
            IngredientCostLine(
                ingredient_id=line.ingredient.pk,
                ingredient_name=line.ingredient.name,
                unit=line.ingredient.unit,
                amount=line.amount,
                unit_cost=line.ingredient.cost_per_unit,
                line_cost=_round_money(raw_line_cost),
                cost_share_pct=cost_share_pct,
                stock_quantity=line.ingredient.stock_quantity,
                available_portions=available_portions,
                is_limiting=(available_portions == max_portions),
                is_out_of_stock=(available_portions == 0),
            )
        )

    return cost_lines, raw_total_cost, max_portions


def calculate_recipe_costing(
    lines: Iterable[RecipeLineInput],
    price: Decimal,
    target_food_cost_pct: Decimal = Decimal("25.00"),
) -> DrinkCosting:
    """Calculate full costing, margin, food cost, and stock availability."""
    price_decimal = Decimal(price)
    target_pct_decimal = Decimal(target_food_cost_pct)
    if price_decimal < ZERO:
        raise ValueError("Drink price cannot be negative.")
    if target_pct_decimal <= ZERO or target_pct_decimal > HUNDRED:
        raise ValueError(
            "Target food cost percentage must be between 0 and 100."
        )

    aggregated_lines = _aggregate_lines(lines)
    cost_lines, raw_total_cost, max_portions = _build_cost_lines(
        aggregated_lines
    )

    cost_price = _round_money(raw_total_cost)
    gross_margin = _round_money(price_decimal - cost_price)
    food_cost_pct = (
        _round_money((cost_price / price_decimal) * HUNDRED)
        if price_decimal > ZERO
        else Decimal("0.00")
    )
    food_cost_zone = _classify_food_cost(food_cost_pct)
    markup_pct = (
        _round_money(((price_decimal - cost_price) / cost_price) * HUNDRED)
        if cost_price > ZERO
        else None
    )
    recommended_price = (
        _round_money((cost_price * HUNDRED) / target_pct_decimal)
        if cost_price > ZERO
        else Decimal("0.00")
    )

    total_ml = sum(
        (
            line.amount
            for line in aggregated_lines
            if line.ingredient.unit == BarIngredient.Unit.ML
        ),
        ZERO,
    )
    estimated_volume_ml = int(
        total_ml.to_integral_value(rounding=ROUND_HALF_UP)
    )

    return DrinkCosting(
        price=_round_money(price_decimal),
        target_food_cost_pct=_round_money(target_pct_decimal),
        cost_price=cost_price,
        gross_margin=gross_margin,
        food_cost_pct=food_cost_pct,
        food_cost_zone=food_cost_zone,
        markup_pct=markup_pct,
        recommended_price=recommended_price,
        estimated_volume_ml=estimated_volume_ml,
        max_portions=max_portions,
        availability_status=_classify_availability(max_portions),
        lines=tuple(cost_lines),
    )


def calculate_drink_costing(drink: Drink) -> DrinkCosting:
    """Calculate costing for a saved Drink using its recipe_items."""
    recipe_lines = [
        RecipeLineInput(
            ingredient=recipe_item.ingredient,
            amount=recipe_item.amount,
        )
        for recipe_item in drink.recipe_items.all()
    ]
    return calculate_recipe_costing(
        recipe_lines,
        price=drink.price,
        target_food_cost_pct=drink.target_food_cost_pct,
    )


def calculate_drinks_costing_map(
    drinks: Iterable[Drink],
) -> dict[int, DrinkCosting]:
    """Compute costing dictionary keyed by drink PK for prefetched drinks."""
    return {drink.pk: calculate_drink_costing(drink) for drink in drinks}


def calculate_drink_unit_cost(drink: Drink) -> Decimal:
    """Return unrounded-to-cents (4-decimal) recipe unit cost for snapshots."""
    raw_total_cost = sum(
        (
            recipe_item.amount * recipe_item.ingredient.cost_per_unit
            for recipe_item in drink.recipe_items.all()
        ),
        ZERO,
    )
    return _round_unit_cost(raw_total_cost)
