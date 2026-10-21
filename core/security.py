"""core/security.py -- shared permission tiers, audit log and safety lock.

Every scenario (transfer, cards, subscriptions, wealth...) can reuse this.

Tiers (from the competition brief):
  auto     read-only queries, run directly (no pending record needed)
  confirm  low-risk actions: show details, user must confirm
  strong   high-risk actions: user must confirm AND pass strong verification
           (face / SMS code / U-shield -- mocked here by DEMO_VERIFICATION_CODE)

Design rule (prompt-injection defence):
  The LLM/agent may only call the *request_* / *apply_* style functions, which
  create a PENDING action. Only the UI (a real button press + code input)
  should call confirm_pending(). So a clever prompt can never skip a tier.

All functions return the repo-wide format: {status, data, txn_id, error}.
"""
import datetime
import itertools

LEVEL_AUTO = "auto"
LEVEL_CONFIRM = "confirm"
LEVEL_STRONG = "strong"

DEMO_VERIFICATION_CODE = "123456"  # stand-in for SMS / face / U-shield
MAX_FAILED_VERIFICATIONS = 3
LOCK_MESSAGE = "账户已因多次验证失败被安全锁定，请联系人工客服"

_pending = {}
_executors = {}
_audit_log = []
_seq = itertools.count(1)
_state = {"failed": 0, "locked": False}


# ---------- response helpers (match docs/data_shapes.md) ----------
def ok(data=None, txn_id=None):
    return {"status": "success", "data": data or {}, "txn_id": txn_id, "error": None}


def fail(error, data=None):
    return {"status": "failed", "data": data or {}, "txn_id": None, "error": error}


# ---------- audit log ----------
def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def audit(action, detail, result):
    """Record every key operation (who/what/outcome) for the audit requirement."""
    _audit_log.append({"time": _now(), "action": action, "detail": detail, "result": result})


def get_audit_log():
    return ok({"entries": list(_audit_log)})


# ---------- circuit breaker ----------
def is_locked():
    return _state["locked"]


def reset_lock():
    """Demo/admin only: unlock after the circuit breaker tripped."""
    _state["failed"] = 0
    _state["locked"] = False
    audit("security_unlock", {}, "unlocked")
    return ok({"locked": False})


def reset_all():
    """For tests/demo: wipe pending items, audit log and lock state."""
    _pending.clear()
    _audit_log.clear()
    _state.update(failed=0, locked=False)


# ---------- pending actions ----------
def register_executor(action, fn):
    """fn(payload) -> response dict. Only runs after confirm_pending() succeeds."""
    _executors[action] = fn


def create_pending(action, payload, level, summary):
    if level not in (LEVEL_CONFIRM, LEVEL_STRONG):
        return fail("无效的权限等级")
    if _state["locked"]:
        audit(action, payload, "blocked:locked")
        return fail(LOCK_MESSAGE)
    pid = f"PEND-{next(_seq):04d}"
    _pending[pid] = {
        "pending_id": pid, "action": action, "payload": payload,
        "level": level, "summary": summary, "status": "pending", "created": _now(),
    }
    audit(action, payload, f"pending:{level}")
    needs_code = level == LEVEL_STRONG
    return ok({
        "pending_id": pid,
        "level": level,
        "summary": summary,
        "needs_code": needs_code,
        "message": ("请核对信息并输入验证码确认：" if needs_code else "请核对信息并确认：") + summary,
    })


def confirm_pending(pending_id, code=None):
    p = _pending.get(pending_id)
    if not p:
        return fail("找不到待确认的操作")
    if p["status"] != "pending":
        return fail(f"该操作已处于「{p['status']}」状态，无法再次确认")
    if _state["locked"]:
        audit(p["action"], {"pending_id": pending_id}, "blocked:locked")
        return fail(LOCK_MESSAGE)

    if p["level"] == LEVEL_STRONG:
        if str(code or "").strip() != DEMO_VERIFICATION_CODE:
            _state["failed"] += 1
            remaining = max(0, MAX_FAILED_VERIFICATIONS - _state["failed"])
            audit(p["action"], {"pending_id": pending_id}, "verification_failed")
            if _state["failed"] >= MAX_FAILED_VERIFICATIONS:
                _state["locked"] = True
                audit("security_lock", {"reason": "too many failed verifications"}, "locked")
                return fail(LOCK_MESSAGE)
            return fail("验证失败", {"remaining_attempts": remaining})
        _state["failed"] = 0

    executor = _executors.get(p["action"])
    if executor is None:
        return fail("系统未注册该操作的执行器")
    try:
        result = executor(p["payload"])
    except Exception as exc:  # never leak internals to the user
        p["status"] = "error"
        audit(p["action"], {"pending_id": pending_id}, f"error:{type(exc).__name__}")
        return fail("执行失败，请稍后重试")

    p["status"] = "done" if result["status"] == "success" else "failed"
    audit(p["action"], {"pending_id": pending_id, **p["payload"]}, result["status"])
    return result


def cancel_pending(pending_id):
    """User interrupts / backs out before anything was executed."""
    p = _pending.get(pending_id)
    if not p or p["status"] != "pending":
        return fail("没有可取消的待确认操作")
    p["status"] = "cancelled"
    audit(p["action"], {"pending_id": pending_id}, "cancelled")
    return ok({"pending_id": pending_id, "status": "cancelled"})


def list_pending():
    items = [dict(p) for p in _pending.values() if p["status"] == "pending"]
    return ok({"pending": items})
