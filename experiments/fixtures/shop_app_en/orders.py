"""Order module: English demo fixture."""

from __future__ import annotations


class OrderService:
    """Order service."""

    def __init__(self, user_service: "UserService"):  # noqa: F821, UP037
        self.user_service = user_service

    async def create_order(
        self,
        user_id: int,
        items: list[dict],
        coupon_code: str | None = None,
    ) -> dict:
        """Create an order and reserve inventory."""
        return {}
