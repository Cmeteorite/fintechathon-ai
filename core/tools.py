# core/tools.py
import datetime

# Fake Database
BALANCE = 5000.00
TRANSACTIONS = [
    {"date": "2026-09-01", "category": "餐饮", "amount": 68.0, "merchant": "麦当劳"},
    {"date": "2026-09-02", "category": "餐饮", "amount": 42.0, "merchant": "瑞幸咖啡"},
    {"date": "2026-09-05", "category": "交通", "amount": 15.0, "merchant": "地铁"},
    {"date": "2026-09-10", "category": "购物", "amount": 299.0, "merchant": "淘宝"},
    {"date": "2026-09-15", "category": "餐饮", "amount": 120.0, "merchant": "海底捞"}
]

def get_balance():
    return {"status": "success", "data": {"balance": BALANCE}, "txn_id": None, "error": None}

def get_transactions(category=None):
    if category:
        filtered = [t for t in TRANSACTIONS if t["category"] == category]
    else:
        filtered = TRANSACTIONS
    return {"status": "success", "data": {"transactions": filtered}, "txn_id": None, "error": None}

def execute_transfer(amount, recipient="Unknown"):
    global BALANCE
    if amount > BALANCE:
        return {"status": "failed", "data": {}, "txn_id": None, "error": "余额不足"}
    
    BALANCE -= amount
    return {
        "status": "success", 
        "data": {"amount": amount, "recipient": recipient, "new_balance": BALANCE}, 
        "txn_id": f"TXN-{datetime.datetime.now().strftime('%H%M%S')}", 
        "error": None
    }


def find_recipient(query):
    from core import transfer
    return transfer.find_recipient(query)


def request_transfer(recipient, amount, note=""):
    from core import transfer
    return transfer.request_transfer(recipient, amount, note)


def schedule_transfer(recipient, amount, run_at, repeat=None):
    from core import transfer
    return transfer.schedule_transfer(recipient, amount, run_at, repeat)


def split_bill(total, participants, include_self=True):
    from core import transfer
    return transfer.split_bill(total, participants, include_self)


def list_cards():
    from core import cards
    return cards.list_cards()


def apply_card(card_type="virtual"):
    from core import cards
    return cards.apply_card(card_type)


def adjust_card_limit(card_id, new_limit):
    from core import cards
    return cards.adjust_limit(card_id, new_limit)


def set_card_restriction(card_id, restriction, enabled):
    from core import cards
    return cards.set_restriction(card_id, restriction, enabled)


def report_card_lost(card_id):
    from core import cards
    return cards.report_lost(card_id)


def unfreeze_card(card_id):
    from core import cards
    return cards.unfreeze_card(card_id)


AGENT_TOOLS = {
    "find_recipient": find_recipient,
    "request_transfer": request_transfer,
    "schedule_transfer": schedule_transfer,
    "split_bill": split_bill,
    "list_cards": list_cards,
    "apply_card": apply_card,
    "adjust_card_limit": adjust_card_limit,
    "set_card_restriction": set_card_restriction,
    "report_card_lost": report_card_lost,
    "unfreeze_card": unfreeze_card,
}