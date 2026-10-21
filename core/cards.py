"""core/cards.py -- Scenario 4: Card Management (卡片管理).

Covers: apply for a card, adjust limit, restrict / unlock transactions, report lost / unfreeze.

Tiers (the brief fixes the strong ones; the rest are our design choice):
    list cards ................................ auto
    apply virtual/physical card ............... confirm
    lower limit / add a restriction ........... confirm   (makes the card safer)
    raise limit / remove a restriction ........ strong    (makes the card riskier)
    report lost (挂失) / unfreeze (解挂) ........ strong    (stated in the brief)
"""
import random

from core import security as sec

MAX_LIMIT = 50000.0
RESTRICTION_TYPES = ("online", "overseas", "atm")  # True = this kind of transaction is BLOCKED
_RESTRICTION_NAMES = {"online": "网上支付", "overseas": "境外交易", "atm": "ATM 取现"}

CARDS = {}


def _seed():
    CARDS.clear()
    CARDS["C001"] = {"card_id": "C001", "last4": "8841", "type": "debit", "status": "active",
                     "daily_limit": 5000.0,
                     "restrictions": {"online": False, "overseas": True, "atm": False}}


_seed()


def _label(card):
    return f"尾号 {card['last4']} 的卡（{card['card_id']}）"


def _get(card_id):
    card = CARDS.get(str(card_id or "").strip())
    if not card:
        return None, sec.fail("找不到这张卡")
    return card, None


def _parse_limit(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")) or v <= 0 or v > MAX_LIMIT:
        return None
    return round(v, 2)


# ---------------------------------------------------------------- query (auto)
def list_cards():
    return sec.ok({"cards": [dict(c, restrictions=dict(c["restrictions"])) for c in CARDS.values()]})


# ---------------------------------------------------------------- apply
def apply_card(card_type="virtual"):
    if card_type not in ("virtual", "physical"):
        return sec.fail("卡类型只能是 virtual（虚拟卡）或 physical（实体卡）")
    name = "虚拟卡" if card_type == "virtual" else "实体卡"
    return sec.create_pending("card_apply", {"card_type": card_type}, sec.LEVEL_CONFIRM,
                              f"申请一张{name}")


def _do_apply(payload):
    new_id = f"C{len(CARDS) + 1:03d}"
    virtual = payload["card_type"] == "virtual"
    CARDS[new_id] = {"card_id": new_id, "last4": str(random.randint(1000, 9999)),
                     "type": payload["card_type"],
                     "status": "active" if virtual else "pending_delivery",
                     "daily_limit": 2000.0 if virtual else 5000.0,
                     "restrictions": {"online": False, "overseas": True, "atm": virtual}}
    return sec.ok({"card": dict(CARDS[new_id])}, txn_id=f"CARD-{new_id}")


# ---------------------------------------------------------------- limit
def adjust_limit(card_id, new_limit):
    card, err = _get(card_id)
    if err:
        return err
    if card["status"] != "active":
        return sec.fail("只有正常状态的卡才能调整额度")
    limit = _parse_limit(new_limit)
    if limit is None:
        return sec.fail(f"额度无效：必须是 0 到 {MAX_LIMIT:.0f} 之间的数字")
    if limit == card["daily_limit"]:
        return sec.fail("新额度与当前额度相同")
    raising = limit > card["daily_limit"]
    level = sec.LEVEL_STRONG if raising else sec.LEVEL_CONFIRM
    summary = f"将{_label(card)}的每日额度从 ¥{card['daily_limit']:.0f} {'提高' if raising else '降低'}到 ¥{limit:.0f}"
    return sec.create_pending("card_limit", {"card_id": card["card_id"], "new_limit": limit},
                              level, summary)


def _do_limit(payload):
    card, err = _get(payload["card_id"])
    if err:
        return err
    if card["status"] != "active":
        return sec.fail("只有正常状态的卡才能调整额度")
    old = card["daily_limit"]
    card["daily_limit"] = payload["new_limit"]
    return sec.ok({"card_id": card["card_id"], "old_limit": old, "new_limit": card["daily_limit"]})


# ---------------------------------------------------------------- restrictions
def set_restriction(card_id, restriction, enabled):
    """enabled=True blocks that kind of transaction; enabled=False unlocks it."""
    card, err = _get(card_id)
    if err:
        return err
    if restriction not in RESTRICTION_TYPES:
        return sec.fail(f"限制类型只能是：{', '.join(RESTRICTION_TYPES)}")
    if card["status"] != "active":
        return sec.fail("只有正常状态的卡才能修改交易限制")
    enabled = enabled is True or str(enabled).lower() in ("true", "1", "yes")
    if card["restrictions"][restriction] == enabled:
        return sec.fail("当前已经是这个状态")
    level = sec.LEVEL_CONFIRM if enabled else sec.LEVEL_STRONG
    summary = f"{'限制' if enabled else '解除限制'}{_label(card)}的{_RESTRICTION_NAMES[restriction]}"
    return sec.create_pending("card_restriction",
                              {"card_id": card["card_id"], "restriction": restriction, "enabled": enabled},
                              level, summary)


def _do_restriction(payload):
    card, err = _get(payload["card_id"])
    if err:
        return err
    if card["status"] != "active":
        return sec.fail("只有正常状态的卡才能修改交易限制")
    card["restrictions"][payload["restriction"]] = payload["enabled"]
    return sec.ok({"card_id": card["card_id"], "restrictions": dict(card["restrictions"])})


# ---------------------------------------------------------------- lost / unfreeze
def report_lost(card_id):
    card, err = _get(card_id)
    if err:
        return err
    if card["status"] != "active":
        return sec.fail(f"这张卡当前状态是「{card['status']}」，无法挂失")
    return sec.create_pending("card_lost", {"card_id": card["card_id"]}, sec.LEVEL_STRONG,
                              f"挂失{_label(card)}（挂失后该卡将无法使用）")


def _do_lost(payload):
    card, err = _get(payload["card_id"])
    if err:
        return err
    if card["status"] != "active":
        return sec.fail("这张卡已不是正常状态")
    card["status"] = "frozen"
    return sec.ok({"card_id": card["card_id"], "status": card["status"]}, txn_id=f"LOST-{card['card_id']}")


def unfreeze_card(card_id):
    card, err = _get(card_id)
    if err:
        return err
    if card["status"] != "frozen":
        return sec.fail("只有已挂失的卡才能解挂")
    return sec.create_pending("card_unfreeze", {"card_id": card["card_id"]}, sec.LEVEL_STRONG,
                              f"解除挂失{_label(card)}")


def _do_unfreeze(payload):
    card, err = _get(payload["card_id"])
    if err:
        return err
    if card["status"] != "frozen":
        return sec.fail("这张卡当前不是挂失状态")
    card["status"] = "active"
    return sec.ok({"card_id": card["card_id"], "status": card["status"]})


# ---------------------------------------------------------------- wiring
sec.register_executor("card_apply", _do_apply)
sec.register_executor("card_limit", _do_limit)
sec.register_executor("card_restriction", _do_restriction)
sec.register_executor("card_lost", _do_lost)
sec.register_executor("card_unfreeze", _do_unfreeze)


def reset_state():
    """For tests/demo."""
    _seed()
