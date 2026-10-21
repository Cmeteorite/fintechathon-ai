"""Test cases for Smart Transfer, Card Management and the shared security layer.

Run from the project root:
    python -m unittest tests/test_angel.py -v
"""
import datetime
import unittest

from app import app
from core import cards, tools, transfer
from core import security as sec

CODE = sec.DEMO_VERIFICATION_CODE


def future(days=1, hour=9):
    d = datetime.datetime.now() + datetime.timedelta(days=days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")


class Base(unittest.TestCase):
    def setUp(self):
        sec.reset_all()
        transfer.reset_state()
        cards.reset_state()
        self.client = app.test_client()

    def assertOk(self, r):
        self.assertEqual(r["status"], "success", r)

    def assertFailed(self, r, contains=None):
        self.assertEqual(r["status"], "failed", r)
        self.assertIsNotNone(r["error"])
        if contains:
            self.assertIn(contains, r["error"])


class TestResponseShape(Base):
    def test_every_response_has_the_four_fields(self):
        for r in (transfer.request_transfer("李明", 10), transfer.request_transfer("李明", -1),
                  cards.list_cards(), cards.report_lost("C001"), sec.get_audit_log()):
            self.assertEqual(set(r), {"status", "data", "txn_id", "error"})
            self.assertIn(r["status"], ("success", "failed"))


class TestRecipientLookup(Base):
    def test_by_name_phone_and_note(self):
        self.assertEqual(transfer.find_recipient("王芳")["data"]["contact"]["name"], "王芳")
        self.assertEqual(transfer.find_recipient("13700003333")["data"]["contact"]["name"], "王芳")
        self.assertEqual(transfer.find_recipient("尾号4444")["data"]["contact"]["name"], "陈雨")
        self.assertEqual(transfer.find_recipient("室友")["data"]["contact"]["name"], "李明")

    def test_exact_name_beats_partial_match(self):
        self.assertEqual(transfer.find_recipient("李明")["data"]["contact"]["name"], "李明")

    def test_ambiguous_returns_candidates_instead_of_guessing(self):
        r = transfer.find_recipient("李")
        self.assertFailed(r, "多个")
        self.assertEqual(len(r["data"]["candidates"]), 2)

    def test_unknown_and_empty(self):
        self.assertFailed(transfer.find_recipient("不存在的人"), "找不到")
        self.assertFailed(transfer.find_recipient(""))

    def test_phone_is_masked(self):
        self.assertEqual(transfer.find_recipient("王芳")["data"]["contact"]["phone"], "137****3333")


class TestTransferValidation(Base):
    def test_rejects_bad_amounts(self):
        for bad in (-500, 0, "abc", None, float("nan"), float("inf"), True, 10 ** 9):
            self.assertFailed(transfer.request_transfer("李明", bad))
        self.assertEqual(tools.BALANCE, 5000.0)

    def test_insufficient_balance(self):
        tools.BALANCE = 100.0
        self.assertFailed(transfer.request_transfer("李明", 500), "余额不足")


class TestPermissionTiers(Base):
    def test_request_never_moves_money(self):
        self.assertOk(transfer.request_transfer("李明", 100))
        self.assertEqual(tools.BALANCE, 5000.0)

    def test_small_transfer_needs_confirm_only(self):
        r = transfer.request_transfer("李明", 1000)  # boundary: exactly 1000 is still small
        self.assertEqual(r["data"]["level"], sec.LEVEL_CONFIRM)
        self.assertFalse(r["data"]["needs_code"])
        done = sec.confirm_pending(r["data"]["pending_id"])
        self.assertOk(done)
        self.assertTrue(done["txn_id"].startswith("TXN-"))
        self.assertEqual(tools.BALANCE, 4000.0)

    def test_large_transfer_needs_strong_verification(self):
        r = transfer.request_transfer("王芳", 1000.01)
        self.assertEqual(r["data"]["level"], sec.LEVEL_STRONG)
        self.assertTrue(r["data"]["needs_code"])
        pid = r["data"]["pending_id"]
        self.assertFailed(sec.confirm_pending(pid), "验证失败")  # no code
        self.assertEqual(tools.BALANCE, 5000.0)
        self.assertOk(sec.confirm_pending(pid, CODE))
        self.assertAlmostEqual(tools.BALANCE, 3999.99)

    def test_daily_total_is_cumulative(self):
        a = transfer.request_transfer("李明", 600)
        self.assertOk(sec.confirm_pending(a["data"]["pending_id"]))
        b = transfer.request_transfer("王芳", 600)  # 600 + 600 > 1000
        self.assertEqual(b["data"]["level"], sec.LEVEL_STRONG)

    def test_two_small_pending_cannot_sneak_past_the_limit(self):
        a = transfer.request_transfer("李明", 600)
        b = transfer.request_transfer("王芳", 600)  # both look small at request time
        self.assertEqual(b["data"]["level"], sec.LEVEL_CONFIRM)
        self.assertOk(sec.confirm_pending(a["data"]["pending_id"]))
        self.assertFailed(sec.confirm_pending(b["data"]["pending_id"]), "1000")
        self.assertEqual(tools.BALANCE, 4400.0)

    def test_pending_cannot_be_confirmed_twice(self):
        r = transfer.request_transfer("李明", 50)
        pid = r["data"]["pending_id"]
        self.assertOk(sec.confirm_pending(pid))
        self.assertFailed(sec.confirm_pending(pid))
        self.assertEqual(tools.BALANCE, 4950.0)

    def test_cancel_before_confirm(self):
        pid = transfer.request_transfer("李明", 50)["data"]["pending_id"]
        self.assertOk(sec.cancel_pending(pid))
        self.assertFailed(sec.confirm_pending(pid))
        self.assertEqual(tools.BALANCE, 5000.0)

    def test_unknown_pending_id(self):
        self.assertFailed(sec.confirm_pending("PEND-9999"))


class TestCircuitBreaker(Base):
    def test_three_wrong_codes_lock_everything(self):
        pid = transfer.request_transfer("王芳", 2000)["data"]["pending_id"]
        r1 = sec.confirm_pending(pid, "000000")
        self.assertEqual(r1["data"]["remaining_attempts"], 2)
        sec.confirm_pending(pid, "111111")
        r3 = sec.confirm_pending(pid, "222222")
        self.assertFailed(r3, "锁定")
        self.assertTrue(sec.is_locked())
        # even the right code is refused now, and new requests are blocked
        self.assertFailed(sec.confirm_pending(pid, CODE), "锁定")
        self.assertFailed(transfer.request_transfer("李明", 10), "锁定")
        self.assertFailed(cards.report_lost("C001"), "锁定")
        self.assertEqual(tools.BALANCE, 5000.0)
        sec.reset_lock()
        self.assertOk(transfer.request_transfer("李明", 10))

    def test_correct_code_resets_failure_counter(self):
        pid = transfer.request_transfer("王芳", 2000)["data"]["pending_id"]
        sec.confirm_pending(pid, "bad")
        sec.confirm_pending(pid, "bad")
        self.assertOk(sec.confirm_pending(pid, CODE))
        pid2 = transfer.request_transfer("王芳", 1500)["data"]["pending_id"]
        self.assertEqual(sec.confirm_pending(pid2, "bad")["data"]["remaining_attempts"], 2)


class TestAuditLog(Base):
    def test_actions_are_recorded(self):
        pid = transfer.request_transfer("李明", 50)["data"]["pending_id"]
        sec.confirm_pending(pid)
        transfer.request_transfer("李明", -5)
        entries = sec.get_audit_log()["data"]["entries"]
        results = [e["result"] for e in entries]
        self.assertIn("pending:confirm", results)
        self.assertIn("success", results)
        self.assertIn("rejected:invalid_amount", results)


class TestScheduledTransfer(Base):
    def test_schedule_requires_confirmation_and_stores_nothing_before(self):
        r = transfer.schedule_transfer("李明", 200, future(), "monthly")
        self.assertOk(r)
        self.assertEqual(transfer.list_scheduled()["data"]["scheduled"], [])
        self.assertOk(sec.confirm_pending(r["data"]["pending_id"]))
        self.assertEqual(len(transfer.list_scheduled()["data"]["scheduled"]), 1)
        self.assertEqual(tools.BALANCE, 5000.0)  # nothing is paid at schedule time

    def test_validation(self):
        self.assertFailed(transfer.schedule_transfer("李明", 200, "yesterday"), "时间格式")
        self.assertFailed(transfer.schedule_transfer("李明", 200, "2020-01-01 09:00"), "未来")
        self.assertFailed(transfer.schedule_transfer("李明", 200, future(), "hourly"), "重复")
        self.assertFailed(transfer.schedule_transfer("李明", -1, future()))

    def _create(self, name, amount, repeat=None):
        r = transfer.schedule_transfer(name, amount, future(), repeat)
        sec.confirm_pending(r["data"]["pending_id"])

    def test_due_transfer_runs_once_and_finishes(self):
        self._create("李明", 200)
        self.assertEqual(transfer.run_due_transfers()["data"]["executed"], [])  # not due yet
        later = datetime.datetime.now() + datetime.timedelta(days=2)
        res = transfer.run_due_transfers(later)
        self.assertEqual(len(res["data"]["executed"]), 1)
        self.assertEqual(tools.BALANCE, 4800.0)
        self.assertEqual(transfer.list_scheduled()["data"]["scheduled"][0]["status"], "done")
        self.assertEqual(transfer.run_due_transfers(later)["data"]["executed"], [])  # no double run

    def test_repeating_schedule_advances(self):
        self._create("李明", 100, "daily")
        first = transfer.list_scheduled()["data"]["scheduled"][0]["next_run"]
        transfer.run_due_transfers(datetime.datetime.now() + datetime.timedelta(days=2))
        entry = transfer.list_scheduled()["data"]["scheduled"][0]
        self.assertEqual(entry["status"], "active")
        self.assertGreater(entry["next_run"], first)

    def test_large_scheduled_transfer_still_needs_strong_verification(self):
        self._create("王芳", 3000)
        res = transfer.run_due_transfers(datetime.datetime.now() + datetime.timedelta(days=2))
        self.assertEqual(res["data"]["executed"], [])
        self.assertEqual(len(res["data"]["needs_verification"]), 1)
        self.assertEqual(tools.BALANCE, 5000.0)  # nothing moved without verification


class TestAAsplit(Base):
    def test_even_split(self):
        r = transfer.split_bill(300, ["李明", "王芳"])
        self.assertOk(r)
        self.assertEqual(r["data"]["my_share"], 100.0)
        self.assertEqual([x["amount"] for x in r["data"]["requests"]], [100.0, 100.0])

    def test_cents_are_exact(self):
        r = transfer.split_bill(100, ["李明", "王芳"])  # 3 people
        self.assertAlmostEqual(sum(r["data"]["shares"].values()), 100.0)

    def test_unknown_friend_is_reported_not_dropped(self):
        r = transfer.split_bill(90, ["李明", "路人甲"])
        self.assertEqual(len(r["data"]["unresolved"]), 1)
        self.assertEqual(r["data"]["shares"]["路人甲"], 30.0)

    def test_validation(self):
        self.assertFailed(transfer.split_bill(0, ["李明"]))
        self.assertFailed(transfer.split_bill(100, []))
        self.assertFailed(transfer.split_bill(100, ["李明", "李明"]), "重复")

    def test_split_moves_no_money(self):
        transfer.split_bill(300, ["李明", "王芳"])
        self.assertEqual(tools.BALANCE, 5000.0)


class TestCards(Base):
    def test_list(self):
        r = cards.list_cards()
        self.assertEqual(r["data"]["cards"][0]["card_id"], "C001")

    def test_apply_virtual_card_needs_confirm(self):
        r = cards.apply_card("virtual")
        self.assertEqual(r["data"]["level"], sec.LEVEL_CONFIRM)
        self.assertEqual(len(cards.CARDS), 1)  # not created yet
        done = sec.confirm_pending(r["data"]["pending_id"])
        self.assertOk(done)
        self.assertEqual(done["data"]["card"]["status"], "active")
        self.assertEqual(len(cards.CARDS), 2)

    def test_apply_invalid_type(self):
        self.assertFailed(cards.apply_card("gold"))

    def test_lower_limit_confirm_raise_limit_strong(self):
        low = cards.adjust_limit("C001", 3000)
        self.assertEqual(low["data"]["level"], sec.LEVEL_CONFIRM)
        self.assertOk(sec.confirm_pending(low["data"]["pending_id"]))
        self.assertEqual(cards.CARDS["C001"]["daily_limit"], 3000.0)
        high = cards.adjust_limit("C001", 8000)
        self.assertEqual(high["data"]["level"], sec.LEVEL_STRONG)
        self.assertFailed(sec.confirm_pending(high["data"]["pending_id"], "bad"))
        self.assertEqual(cards.CARDS["C001"]["daily_limit"], 3000.0)
        self.assertOk(sec.confirm_pending(high["data"]["pending_id"], CODE))
        self.assertEqual(cards.CARDS["C001"]["daily_limit"], 8000.0)

    def test_limit_validation(self):
        for bad in (-1, 0, "abc", None, 10 ** 7, float("nan")):
            self.assertFailed(cards.adjust_limit("C001", bad))
        self.assertFailed(cards.adjust_limit("C001", 5000), "相同")
        self.assertFailed(cards.adjust_limit("NOPE", 100), "找不到")

    def test_restriction_add_confirm_remove_strong(self):
        add = cards.set_restriction("C001", "online", True)
        self.assertEqual(add["data"]["level"], sec.LEVEL_CONFIRM)
        self.assertOk(sec.confirm_pending(add["data"]["pending_id"]))
        self.assertTrue(cards.CARDS["C001"]["restrictions"]["online"])
        rem = cards.set_restriction("C001", "online", False)
        self.assertEqual(rem["data"]["level"], sec.LEVEL_STRONG)
        self.assertOk(sec.confirm_pending(rem["data"]["pending_id"], CODE))
        self.assertFalse(cards.CARDS["C001"]["restrictions"]["online"])

    def test_restriction_validation(self):
        self.assertFailed(cards.set_restriction("C001", "teleport", True))
        self.assertFailed(cards.set_restriction("C001", "overseas", True), "已经")  # already on

    def test_report_lost_requires_strong_verification(self):
        r = cards.report_lost("C001")
        self.assertEqual(r["data"]["level"], sec.LEVEL_STRONG)
        self.assertEqual(cards.CARDS["C001"]["status"], "active")  # not frozen yet
        self.assertFailed(sec.confirm_pending(r["data"]["pending_id"]))
        self.assertEqual(cards.CARDS["C001"]["status"], "active")
        self.assertOk(sec.confirm_pending(r["data"]["pending_id"], CODE))
        self.assertEqual(cards.CARDS["C001"]["status"], "frozen")

    def test_frozen_card_rules(self):
        sec.confirm_pending(cards.report_lost("C001")["data"]["pending_id"], CODE)
        self.assertFailed(cards.report_lost("C001"), "无法挂失")
        self.assertFailed(cards.adjust_limit("C001", 1000), "正常状态")
        self.assertFailed(cards.set_restriction("C001", "atm", True), "正常状态")
        un = cards.unfreeze_card("C001")
        self.assertEqual(un["data"]["level"], sec.LEVEL_STRONG)
        self.assertOk(sec.confirm_pending(un["data"]["pending_id"], CODE))
        self.assertEqual(cards.CARDS["C001"]["status"], "active")

    def test_unfreeze_active_card_is_rejected(self):
        self.assertFailed(cards.unfreeze_card("C001"), "已挂失")


class TestHTTP(Base):
    def post(self, url, body):
        return self.client.post(url, json=body).get_json()

    def test_full_transfer_flow_over_http(self):
        r = self.post("/api/transfer/request", {"recipient": "李明", "amount": 80})
        self.assertOk(r)
        done = self.post("/api/confirm", {"pending_id": r["data"]["pending_id"]})
        self.assertOk(done)
        self.assertEqual(self.client.get("/api/balance").get_json()["data"]["balance"], 4920.0)

    def test_strong_flow_over_http(self):
        r = self.post("/api/cards/lost", {"card_id": "C001"})
        bad = self.post("/api/confirm", {"pending_id": r["data"]["pending_id"], "code": "x"})
        self.assertFailed(bad)
        good = self.post("/api/confirm", {"pending_id": r["data"]["pending_id"], "code": CODE})
        self.assertOk(good)
        self.assertEqual(self.client.get("/api/cards").get_json()["data"]["cards"][0]["status"], "frozen")

    def test_bad_requests_do_not_crash(self):
        for url in ("/api/transfer/request", "/api/transfer/schedule", "/api/transfer/split",
                    "/api/cards/apply", "/api/cards/limit", "/api/cards/restriction",
                    "/api/cards/lost", "/api/cards/unfreeze", "/api/confirm", "/api/cancel"):
            resp = self.client.post(url, data="not json", content_type="text/plain")
            self.assertEqual(resp.status_code, 200, url)
            self.assertIn(resp.get_json()["status"], ("success", "failed"))

    def test_test_panel_page_is_served(self):
        resp = self.client.get("/angel")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("卡片管理", resp.get_data(as_text=True))

    def test_get_endpoints(self):
        for url in ("/api/contacts/search?q=王芳", "/api/cards", "/api/pending", "/api/audit",
                    "/api/transfer/scheduled"):
            self.assertEqual(self.client.get(url).get_json()["status"], "success", url)


if __name__ == "__main__":
    unittest.main()
