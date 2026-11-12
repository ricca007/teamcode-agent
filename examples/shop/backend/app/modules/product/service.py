"""商城商品模块。"""


def get_product(sku: str) -> dict:
    """查询商品价格与库存。"""
    return {"sku": sku, "price": 20.0, "stock": 10}
