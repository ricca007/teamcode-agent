"""用户模块：实验三 / 实验五的评测样例。"""

from __future__ import annotations


class UserRepository:
    """用户仓储。"""

    def find(self, user_id: int) -> dict | None:
        """按 ID 查询用户。"""
        return None


def get_user(user_id: int, include_deleted: bool = False) -> dict:
    """按 ID 获取用户，未找到时返回空字典。"""
    return {}


def normalize_email(email: str) -> str:
    """去掉邮箱两端空白并转小写。"""
    return email.strip().lower()


class UserService:
    """用户服务。"""

    def __init__(self, repo: UserRepository, retries: int = 3):
        self.repo = repo
        self.retries = retries

    async def create(self, email: str, password: str, role: str = "member") -> dict:
        """创建用户并返回脱敏信息。"""
        return {}
