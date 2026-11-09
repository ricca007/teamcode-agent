"""订单模块：实验三 / 实验五的评测样例。"""

from __future__ import annotations


class OrderService:
    """订单服务。"""

    def __init__(self, user_service: "UserService"):  # noqa: F821, UP037
        self.user_service = user_service

    async def create_order(
        self,
        user_id: int,
        items: list[dict],
        coupon_code: str | None = None,
    ) -> dict:
        """创建订单并锁定库存。"""
        return {}
