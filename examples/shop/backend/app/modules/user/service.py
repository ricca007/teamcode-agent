"""商城用户模块；供接口发现与真实测试演示。"""


def get_user(user_id: int) -> dict:
    """获取用户摘要。"""
    return {"id": user_id, "name": f"User {user_id}"}
