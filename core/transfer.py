"""core/transfer.py -- Scenario 1: Smart Transfer (智能转账).

Covers: transfer by name / phone / note, scheduled transfer, AA bill split.
Permission rule (daily cumulative total, including this transfer):
    <= 1000 CNY  -> confirm   (user confirms the shown details)
    >  1000 CNY  -> strong    (confirm + verification code)

Flow for the agent:  request_transfer(...)  ->  UI calls security.confirm_pending(...)
"""
import calendar
import datetime
import itertools
import math
import re

from core import tools
from core import security as sec

DAILY_LIMIT = 1000.0
MAX_SINGLE = 50000.0
REPEATS = (None, "daily", "weekly", "monthly")

# Fake contact book (replace with real data later)
CONTACTS = [
    {"name": "李明", "phone": "13800001111", "note": "室友"},
    {"name": "李明辉", "phone": "13900002222", "note": "同学"},
    {"name": "王芳", "phone": "13700003333", "note": "组长"},
    {"name": "陈雨", "phone": "13600004444", "note": "旅行AA"},
]

_daily = {}          # "YYYY-MM-DD" -> total transferred that day
SCHEDULED = []       # confirmed scheduled transfers
_txn_seq = itertools.count(1)
_sch_seq = itertools.count(1)


# ---------------------------------------------------------------- helpers
def _mask_phone(phone):
    return phone[:3] + "****" + phone[-4:]


def _public(c):
    return {"name": c["name"], "phone": _mask_phone(c["phone"]), "note": c["note"]}


def _parse_amount(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return round(v, 2)


def _today():
    return datetime.date.today().isoformat()


def today_total():
    return _daily.get(_today(), 0.0)


def level_for(amount):
    """Tier for a transfer, based on the daily cumulative total."""
    return sec.LEVEL_STRONG if today_total() + amount > DAILY_LIMIT else sec.LEVEL_CONFIRM


def _resolve(query):
    """Find exactly one contact by name / phone / note. Returns (contact, error_response)."""
    q = str(query or "").strip()
    if not q:
        return None, sec.fail("请提供收款人（姓名、手机号或备注）")
    digits = re.sub(r"\D", "", q)
    matches = [c for c in CONTACTS if c["name"] == q or (digits and c["phone"] == digits)]
    if not matches:
        matches = [c for c in CONTACTS
                   if q in c["name"] or q in c["note"]
                   or (len(digits) >= 4 and c["phone"].endswith(digits))]
    if not matches:
        return None, sec.fail(f"找不到联系人：{q}")
    if len(matches) > 1:  # never guess -- ask the user
        return None, sec.fail("找到多个匹配的联系人，请指定是哪一位",
                              {"candidates": [_public(c) for c in matches]})
    return matches[0], None


def find_recipient(query):
    """Read-only lookup (auto tier)."""
    contact, err = _resolve(query)
    return err or sec.ok({"contact": _public(contact)})


# ---------------------------------------------------------------- transfer
def request_transfer(recipient_query, amount, note=""):
    """Step 1: validate and create a PENDING transfer. Never moves money."""
    amt = _parse_amount(amount)
    if amt is None:
        sec.audit("transfer", {"amount": str(amount)}, "rejected:invalid_amount")
        return sec.fail("金额无效：必须是大于 0 的数字")
    if amt > MAX_SINGLE:
        return sec.fail(f"单笔金额不能超过 {MAX_SINGLE:.0f} 元")
    contact, err = _resolve(recipient_query)
    if err:
        return err
    if amt > tools.BALANCE:
        return sec.fail("余额不足")
    level = level_for(amt)
    summary = f"向 {contact['name']}（{_mask_phone(contact['phone'])}）转账 ¥{amt:.2f}"
    payload = {"recipient": contact["name"], "phone": _mask_phone(contact["phone"]),
               "amount": amt, "note": str(note or ""), "level": level}
    return sec.create_pending("transfer", payload, level, summary)


def _do_transfer(payload):
    amt = payload["amount"]
    if amt > tools.BALANCE:
        return sec.fail("余额不足")
    # Re-check: another transfer may have pushed today's total over the limit
    if payload["level"] == sec.LEVEL_CONFIRM and today_total() + amt > DAILY_LIMIT:
        return sec.fail("今日累计转账已超过 1000 元，请重新发起并完成强验证")
    tools.BALANCE = round(tools.BALANCE - amt, 2)
    _daily[_today()] = round(today_total() + amt, 2)
    txn_id = f"TXN-{datetime.datetime.now().strftime('%H%M%S')}-{next(_txn_seq):03d}"
    return sec.ok({"amount": amt, "recipient": payload["recipient"],
                   "new_balance": tools.BALANCE, "today_total": today_total()}, txn_id=txn_id)


# ---------------------------------------------------------------- scheduled
def schedule_transfer(recipient_query, amount, run_at, repeat=None):
    """Create a PENDING scheduled transfer. run_at like '2026-11-01 09:00'."""
    amt = _parse_amount(amount)
    if amt is None:
        return sec.fail("金额无效：必须是大于 0 的数字")
    if amt > MAX_SINGLE:
        return sec.fail(f"单笔金额不能超过 {MAX_SINGLE:.0f} 元")
    if repeat not in REPEATS:
        return sec.fail("重复周期只能是 daily / weekly / monthly 或留空")
    try:
        when = datetime.datetime.fromisoformat(str(run_at).strip()).replace(tzinfo=None)
    except ValueError:
        return sec.fail("时间格式无效，请使用例如 2026-11-01 09:00")
    if when <= datetime.datetime.now():
        return sec.fail("定时转账的时间必须在未来")
    contact, err = _resolve(recipient_query)
    if err:
        return err
    when_s = when.isoformat(timespec="minutes")
    summary = (f"定时向 {contact['name']}（{_mask_phone(contact['phone'])}）转账 ¥{amt:.2f}，"
               f"首次执行 {when_s}" + (f"，每{ {'daily': '天', 'weekly': '周', 'monthly': '月'}[repeat] }重复" if repeat else ""))
    payload = {"recipient": contact["name"], "phone": _mask_phone(contact["phone"]),
               "amount": amt, "next_run": when_s, "repeat": repeat}
    return sec.create_pending("schedule_transfer", payload, sec.LEVEL_CONFIRM, summary)


def _do_schedule(payload):
    entry = dict(payload, schedule_id=f"SCH-{next(_sch_seq):03d}", status="active")
    SCHEDULED.append(entry)
    return sec.ok({"schedule_id": entry["schedule_id"], "next_run": entry["next_run"],
                   "repeat": entry["repeat"]})


def list_scheduled():
    return sec.ok({"scheduled": [dict(s) for s in SCHEDULED]})


def _advance(dt, repeat):
    if repeat == "daily":
        return dt + datetime.timedelta(days=1)
    if repeat == "weekly":
        return dt + datetime.timedelta(days=7)
    if repeat == "monthly":
        y, m = dt.year + dt.month // 12, dt.month % 12 + 1
        return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))
    return None


def run_due_transfers(now=None):
    """Run schedules that are due (call from a timer). Small ones run as pre-confirmed;
    ones that would exceed the daily limit become STRONG pending items instead."""
    now = now or datetime.datetime.now()
    executed, needs_verification, failed = [], [], []
    for s in SCHEDULED:
        if s["status"] != "active" or datetime.datetime.fromisoformat(s["next_run"]) > now:
            continue
        if sec.is_locked():
            break
        amt = s["amount"]
        payload = {"recipient": s["recipient"], "phone": s["phone"], "amount": amt,
                   "note": f"定时转账 {s['schedule_id']}", "level": level_for(amt)}
        if payload["level"] == sec.LEVEL_STRONG:
            res = sec.create_pending("transfer", payload, sec.LEVEL_STRONG,
                                     f"定时转账 {s['schedule_id']}：向 {s['recipient']} 转账 ¥{amt:.2f}（超出每日限额，需强验证）")
            needs_verification.append({"schedule_id": s["schedule_id"],
                                       "pending_id": res["data"].get("pending_id")})
        else:
            res = _do_transfer(payload)
            sec.audit("scheduled_transfer_run", {"schedule_id": s["schedule_id"], "amount": amt}, res["status"])
            (executed if res["status"] == "success" else failed).append(
                {"schedule_id": s["schedule_id"], "txn_id": res["txn_id"], "error": res["error"]})
        nxt = _advance(datetime.datetime.fromisoformat(s["next_run"]), s["repeat"])
        if nxt:
            s["next_run"] = nxt.isoformat(timespec="minutes")
        else:
            s["status"] = "done"
    return sec.ok({"executed": executed, "needs_verification": needs_verification, "failed": failed})


# ---------------------------------------------------------------- AA split
def split_bill(total, participants, include_self=True):
    """Compute equal shares (cents-exact) and the payment requests. Moves no money."""
    t = _parse_amount(total)
    if t is None:
        return sec.fail("总金额无效：必须是大于 0 的数字")
    names = [str(n).strip() for n in (participants or []) if str(n).strip()]
    if not names:
        return sec.fail("请提供至少一位参与 AA 的朋友")
    if len(set(names)) != len(names):
        return sec.fail("参与者名单中有重复姓名")
    people = (["我"] if include_self else []) + names
    cents = round(t * 100)
    base, rem = divmod(cents, len(people))
    shares = {p: (base + (1 if i < rem else 0)) / 100 for i, p in enumerate(people)}
    requests, unresolved = [], []
    for n in names:
        contact, err = _resolve(n)
        if err:
            unresolved.append({"name": n, "reason": err["error"]})
        else:
            requests.append({"to": contact["name"], "phone": _mask_phone(contact["phone"]),
                             "amount": shares[n]})
    sec.audit("split_bill", {"total": t, "people": len(people)}, "computed")
    return sec.ok({"total": t, "shares": shares, "my_share": shares.get("我"),
                   "requests": requests, "unresolved": unresolved})


# ---------------------------------------------------------------- wiring
sec.register_executor("transfer", _do_transfer)
sec.register_executor("schedule_transfer", _do_schedule)


def reset_state():
    """For tests/demo."""
    _daily.clear()
    SCHEDULED.clear()
    tools.BALANCE = 5000.00
