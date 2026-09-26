"""
Tiny sample project used by BlastRadius for demo purposes.
"""

def calculate_total(prices: list[float]) -> float:
    """Sum all prices."""
    return sum(prices)


def apply_discount(total: float, percent: float) -> float:
    """Apply a percentage discount."""
    if percent < 0 or percent > 100:
        raise ValueError("Discount must be between 0 and 100")
    return total * (1 - percent / 100)


def format_price(value: float) -> str:
    return f"${value:.2f}"


def checkout(cart: list[float], discount: float = 0) -> str:
    """
    Main checkout flow.
    This function calls both calculate_total and apply_discount.
    """
    total = calculate_total(cart)
    final = apply_discount(total, discount)
    return format_price(final)


def process_order(items: list[float]) -> dict:
    """Another place that uses calculate_total."""
    subtotal = calculate_total(items)
    return {
        "subtotal": subtotal,
        "tax": subtotal * 0.08,
        "total": subtotal * 1.08
    }