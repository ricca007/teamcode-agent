import ast
from pathlib import Path

from backend.app.modules.order.service import create_order
from backend.app.modules.product.service import get_product
from backend.app.modules.user.service import get_user


def test_user():
    assert get_user(7)["id"] == 7


def test_product():
    assert get_product("book")["stock"] >= 0


def test_order_integration():
    order = create_order(7, "book")
    assert order["user"]["id"] == 7 and order["product"]["sku"] == "book"


def test_python_sources_parse():
    for source in Path("backend").rglob("*.py"):
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
