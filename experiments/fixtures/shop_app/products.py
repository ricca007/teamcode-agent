"""商品模块：实验三 / 实验五的评测样例。"""

from __future__ import annotations


class ProductService:
    """商品服务。"""

    def __init__(self, repo: "ProductRepository"):  # noqa: F821, UP037
        self.repo = repo

    def adjust_stock(self, sku: str, delta: int) -> int:
        """调整库存并返回调整后的数量。"""
        return 0


def list_products(category: str | None = None, limit: int = 20) -> list[dict]:
    """按分类分页查询商品。"""
    return []
