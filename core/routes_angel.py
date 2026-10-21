"""core/routes_angel.py -- HTTP endpoints for Smart Transfer + Card Management + shared security.

Register in app.py with two lines:
    from core.routes_angel import bp as angel_bp
    app.register_blueprint(angel_bp)
"""
from flask import Blueprint, jsonify, render_template, request

from core import cards, transfer
from core import security as sec

bp = Blueprint("angel", __name__)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ---------------- test panel (buttons instead of curl) ----------------
@bp.route("/angel")
def angel_page():
    return render_template("angel.html")


# ---------------- smart transfer ----------------
@bp.route("/api/contacts/search", methods=["GET"])
def contacts_search():
    return jsonify(transfer.find_recipient(request.args.get("q", "")))


@bp.route("/api/transfer/request", methods=["POST"])
def transfer_request():
    b = _body()
    return jsonify(transfer.request_transfer(b.get("recipient"), b.get("amount"), b.get("note", "")))


@bp.route("/api/transfer/schedule", methods=["POST"])
def transfer_schedule():
    b = _body()
    return jsonify(transfer.schedule_transfer(b.get("recipient"), b.get("amount"),
                                              b.get("run_at"), b.get("repeat")))


@bp.route("/api/transfer/scheduled", methods=["GET"])
def transfer_scheduled():
    return jsonify(transfer.list_scheduled())


@bp.route("/api/transfer/run-due", methods=["POST"])
def transfer_run_due():
    return jsonify(transfer.run_due_transfers())


@bp.route("/api/transfer/split", methods=["POST"])
def transfer_split():
    b = _body()
    return jsonify(transfer.split_bill(b.get("total"), b.get("participants"), b.get("include_self", True)))


# ---------------- card management ----------------
@bp.route("/api/cards", methods=["GET"])
def cards_list():
    return jsonify(cards.list_cards())


@bp.route("/api/cards/apply", methods=["POST"])
def cards_apply():
    return jsonify(cards.apply_card(_body().get("card_type", "virtual")))


@bp.route("/api/cards/limit", methods=["POST"])
def cards_limit():
    b = _body()
    return jsonify(cards.adjust_limit(b.get("card_id"), b.get("new_limit")))


@bp.route("/api/cards/restriction", methods=["POST"])
def cards_restriction():
    b = _body()
    return jsonify(cards.set_restriction(b.get("card_id"), b.get("restriction"), b.get("enabled")))


@bp.route("/api/cards/lost", methods=["POST"])
def cards_lost():
    return jsonify(cards.report_lost(_body().get("card_id")))


@bp.route("/api/cards/unfreeze", methods=["POST"])
def cards_unfreeze():
    return jsonify(cards.unfreeze_card(_body().get("card_id")))


# ---------------- shared: confirm / cancel / audit ----------------
# NOTE: /api/confirm must be called by the UI (button + code box), never by the LLM agent.
@bp.route("/api/confirm", methods=["POST"])
def confirm():
    b = _body()
    return jsonify(sec.confirm_pending(b.get("pending_id"), b.get("code")))


@bp.route("/api/cancel", methods=["POST"])
def cancel():
    return jsonify(sec.cancel_pending(_body().get("pending_id")))


@bp.route("/api/pending", methods=["GET"])
def pending():
    return jsonify(sec.list_pending())


@bp.route("/api/audit", methods=["GET"])
def audit_log():
    return jsonify(sec.get_audit_log())


@bp.route("/api/security/reset-lock", methods=["POST"])
def reset_lock():  # demo only -- remove or protect before any real use
    return jsonify(sec.reset_lock())
