"""Product module: English demo fixture."""

from __future__ import annotations


class ProductService:
    """Product service."""

    def __init__(self, repo: "ProductRepository"):  # noqa: F821, UP037
        self.repo = repo

    def adjust_stock(self, sku: str, delta: int) -> int:
        """Adjust stock and return the new quantity."""
        return 0


def list_products(category: str | None = None, limit: int = 20) -> list[dict]:
    """List products by category with pagination."""
    return []
