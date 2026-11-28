"""User module: English demo fixture."""

from __future__ import annotations


class UserRepository:
    """User repository."""

    def find(self, user_id: int) -> dict | None:
        """Look up a user by ID."""
        return None


def get_user(user_id: int, include_deleted: bool = False) -> dict:
    """Return a user by ID, or an empty dict when missing."""
    return {}


def normalize_email(email: str) -> str:
    """Trim and lowercase an email address."""
    return email.strip().lower()


class UserService:
    """User service."""

    def __init__(self, repo: UserRepository, retries: int = 3):
        self.repo = repo
        self.retries = retries

    async def create(self, email: str, password: str, role: str = "member") -> dict:
        """Create a user and return a redacted record."""
        return {}
