import re

MODULE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "user",
        ("user", "account", "login", "auth", "profile", "用户", "账户", "登录", "认证"),
    ),
    (
        "product",
        ("product", "catalog", "inventory", "item", "商品", "产品", "库存", "目录"),
    ),
    (
        "coupon",
        ("coupon", "discount", "voucher", "优惠券", "折扣", "满减"),
    ),
    (
        "order",
        ("order", "checkout", "cart", "payment", "订单", "购物车", "结算", "支付"),
    ),
    (
        "interface",
        ("interface", "api contract", "ast", "接口", "契约", "签名"),
    ),
    (
        "agent",
        ("agent", "planning", "coding", "智能体", "代理", "规划", "编排"),
    ),
    (
        "frontend",
        ("frontend", "dashboard", "react", "ui", "前端", "页面", "控制台", "仪表盘"),
    ),
)

MODULE_ORDER = (
    "user",
    "product",
    "coupon",
    "order",
    "interface",
    "agent",
    "frontend",
    "core",
)

MODULE_LABELS = {
    "user": "User",
    "product": "Product",
    "coupon": "Coupon",
    "order": "Order",
    "interface": "Interface",
    "agent": "Agent",
    "frontend": "Frontend",
    "core": "Core",
}

_LIST_PREFIX = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])|[\r\n]+")


def normalize_requirements(requirements: str) -> list[str]:
    normalized: list[str] = []
    for raw_part in _SENTENCE_BOUNDARY.split(requirements):
        part = _LIST_PREFIX.sub("", raw_part).strip()
        if part:
            normalized.append(part)

    if not normalized:
        raise ValueError("requirements must contain at least one non-empty item")
    return normalized


def classify_requirement(requirement: str) -> list[str]:
    lowered = requirement.lower()
    modules = [
        module
        for module, keywords in MODULE_RULES
        if any(_contains_keyword(lowered, keyword) for keyword in keywords)
    ]
    return modules or ["core"]


def group_requirements(requirements: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    unclassified: list[str] = []
    for requirement in requirements:
        modules = classify_requirement(requirement)
        if modules == ["core"]:
            unclassified.append(requirement)
        for module in modules:
            if module == "core":
                continue
            grouped.setdefault(module, []).append(requirement)

    if not grouped:
        grouped["core"] = unclassified
    return grouped


def ordered_modules(grouped: dict[str, list[str]]) -> list[str]:
    rank = {module: index for index, module in enumerate(MODULE_ORDER)}
    return sorted(grouped, key=lambda module: (rank.get(module, len(rank)), module))


def _contains_keyword(requirement: str, keyword: str) -> bool:
    if any(character.isascii() is False for character in keyword):
        return keyword in requirement
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?:s|es)?(?![a-z0-9])"
    return re.search(pattern, requirement) is not None
