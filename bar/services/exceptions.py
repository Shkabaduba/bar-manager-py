from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StockDeficit:
    """Describes a single ingredient shortfall during order checkout."""

    ingredient_id: int
    ingredient_name: str
    unit: str
    required: Decimal
    available: Decimal
    shortfall: Decimal


class BarServiceError(Exception):
    """Base exception for bar business-logic failures."""


class InvalidQuantityError(BarServiceError):
    """Raised when a quantity, amount, or cost input violates invariants."""


class OrderStateError(BarServiceError):
    """Raised when an operation is invalid for the current order status."""


class OrderAlreadyClosedError(OrderStateError):
    """Raised when attempting to close or pay an already finalized order."""


class OptimisticLockError(BarServiceError):
    """Raised when concurrent edits conflict on order version."""


class InsufficientStockError(BarServiceError):
    """Raised when stock cannot cover an order without manager override."""

    def __init__(
        self,
        deficits: list[StockDeficit],
        message: str | None = None,
    ):
        self.deficits = tuple(deficits)
        if message is None:
            names = ", ".join(
                deficit.ingredient_name for deficit in self.deficits
            )
            message = f"Insufficient stock for: {names}."
        super().__init__(message)
