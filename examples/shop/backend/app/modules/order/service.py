"""商城订单模块；导入调用用于展示接口依赖。"""

from backend.app.modules.product.service import get_product
from backend.app.modules.user.service import get_user


def create_order(user_id: int, sku: str) -> dict:
    """根据用户和商品信息创建订单摘要。"""
    return {"user": get_user(user_id), "product": get_product(sku), "status": "created"}
