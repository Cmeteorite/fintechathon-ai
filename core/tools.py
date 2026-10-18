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