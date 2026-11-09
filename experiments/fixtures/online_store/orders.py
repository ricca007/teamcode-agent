class OrderService:
    def create_order(self, user_id: str, product_ids: list[str]) -> dict[str, str]:
        return {"user_id": user_id, "status": "created"}
