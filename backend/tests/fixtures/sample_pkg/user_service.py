"""用户模块：用于验证 AST 提取的各项能力。"""

from __future__ import annotations


def cache(func):
    """极简装饰器，不改变被装饰函数。"""
    return func


def normalize_name(value: str, *, strip: bool = True) -> str:
    """规范化用户名。"""
    return value.strip() if strip else value


def collect_tags(*tags: str, limit: int = 10, **extra: str) -> list[str]:
    """收集标签。"""
    return list(tags)[:limit]


class UserRepository:
    """仅用于类型标注的占位类（夹具不关心具体实现）。"""


class UserService:
    """用户服务。"""

    DEFAULT_ROLE: str = "member"

    def __init__(self, repo: UserRepository, retries: int = 3):
        self.repo = repo
        self.retries = retries

    @cache
    def get_user(self, user_id: int, include_deleted: bool = False) -> dict | None:
        """按 ID 获取用户。"""

        def _inner(uid: int) -> dict:
            return {"id": uid}

        return _inner(user_id)

    async def fetch_remote(self, url: str) -> bytes:
        """异步拉取远程数据。"""
        return b""

    class Meta:
        """嵌套类。"""

        table = "users"
