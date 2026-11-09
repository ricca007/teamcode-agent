class UserService:
    def get_user(self, user_id: str) -> dict[str, str]:
        return {"user_id": user_id}
