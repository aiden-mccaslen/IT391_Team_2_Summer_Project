# route logout back to signup (and add the "you have logged out popup")

import logging
import os
import threading
import time
from collections import deque
from logging.handlers import RotatingFileHandler

from  flask import request, Flask, jsonify, url_for, redirect
from flask_cors import CORS
import user as user_file
import kakeibo_ai
import chat_history
import expenses
import budget
import fee_monitor
import purchase_rules
import reflections
import reports

# The companion widget is entirely optional: nothing else in the backend
# imports this module, so if companion.py (or its migration) is ever deleted,
# the only thing that should notice is the companion routes themselves --
# never the rest of the app. Guarding the import is what makes that true: an
# un-guarded `import companion` would crash the whole process on startup the
# moment the file was gone.
try:
    import companion
except ImportError:
    companion = None


# All backend logging lands in Backend/logs/app.log (rotated at ~1MB so it can
# never grow without bound). The AI layer logs the real API exceptions here;
# users only ever see the friendly one-liners.
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

try:
    os.makedirs(LOG_DIR, exist_ok=True)
    _log_handler = RotatingFileHandler(os.path.join(LOG_DIR, "app.log"),
                                       maxBytes=1_000_000, backupCount=3,
                                       encoding="utf-8")
except OSError:
    # An unwritable app directory must not stop the app from booting -- losing
    # the log file is survivable, taking login/signup down with it is not.
    _log_handler = logging.StreamHandler()

_log_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_log_handler)

# Root stays at WARNING on purpose: httpx logs an INFO line for every Supabase
# and OpenAI request (roughly six per /chat), which would push the AI tracebacks
# -- the only record of what actually went wrong -- out of the rotation. Our own
# loggers are turned up to INFO individually.
logging.getLogger().setLevel(logging.WARNING)
logging.getLogger("kakeibo").setLevel(logging.INFO)
log = logging.getLogger("kakeibo.app")


# Serving the frontend from Flask keeps everything on one origin, so the browser
# is not making cross-origin calls to our own API.
app = Flask(__name__, static_folder="../Frontend", static_url_path="")
CORS(app) # change this to restrict endpoints later

# Off switch for the companion widget, independent of whether the module import
# above succeeded -- COMPANION_ENABLED lets it be turned off without removing
# the file, and `companion is None` covers the file being deleted outright.
# Either one turns off the routes below and makes /health/companion report
# false; every other route in this file is unaffected either way. Defaults to
# enabled, same convention as the AI layer's own env-var checks.
COMPANION_ENABLED = companion is not None and os.environ.get(
    "COMPANION_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


# ---------------------------------------------------------------------------
# Spending guards.
#
# The real backstop is the hard budget limit set in the OpenAI dashboard; these
# just stop one user (or a frontend bug stuck in a retry loop) from eating it.
# Counters live in memory, so restarting Flask resets them -- fine at testing
# scale, precisely because the dashboard limit is the actual ceiling.
# ---------------------------------------------------------------------------
COOLDOWN_MESSAGES = 10        # coach replies allowed...
COOLDOWN_WINDOW = 30 * 60     # ...per this many seconds, per user

# Roughly a dollar per user per month on gpt-4o, which is what DEFAULT_MODEL
# falls back to -- about a tenth of that if KAKEIBO_MODEL is set to gpt-4o-mini.
MONTHLY_MESSAGE_CAP = 100

MAX_MESSAGE_CHARS = 1000      # "one paragraph"

# Guarded by _spend_lock: Flask serves requests on threads, so a check in one
# thread and a claim in another must not interleave.
_spend_lock = threading.Lock()
_recent_sends = {}    # user_id -> deque of timestamps of claimed replies
_monthly_counts = {}  # user_id -> replies claimed this month
_counts_month = None  # which "YYYY-MM" _monthly_counts is for


def reserve_send(user_id):
    """Check this user's limits and, if they pass, claim one slot -- atomically.

    Claiming BEFORE the model call rather than counting successes after it is
    deliberate:
      - concurrent requests can no longer all pass the check and then spend, and
      - failures that still cost money (a refusal, a reply truncated to nothing)
        get counted, which is exactly the runaway case this guard exists for.
    Failures we know were free hand the slot back via release_send().

    Returns None if the send may proceed, or a ready-to-return (response, status)
    pair if the user is on cooldown / out of monthly budget.
    """
    global _counts_month
    now = time.time()

    with _spend_lock:
        this_month = time.strftime("%Y-%m")
        if this_month != _counts_month:
            _counts_month = this_month
            _monthly_counts.clear()

        timestamps = _recent_sends.get(user_id)
        if timestamps is not None:
            while timestamps and now - timestamps[0] > COOLDOWN_WINDOW:
                timestamps.popleft()
            if not timestamps:
                # Drop the key instead of leaving an empty deque behind for
                # every user the server has ever seen.
                del _recent_sends[user_id]
                timestamps = None

        if timestamps and len(timestamps) >= COOLDOWN_MESSAGES:
            minutes_left = int((COOLDOWN_WINDOW - (now - timestamps[0])) // 60) + 1
            return jsonify({
                "success": False,
                "message": f"You've hit the message limit for now -- the coach "
                           f"will be back in about {minutes_left} minutes."
            }), 429

        if _monthly_counts.get(user_id, 0) >= MONTHLY_MESSAGE_CAP:
            return jsonify({
                "success": False,
                "message": "You've used this month's coaching messages. "
                           "They reset at the start of next month."
            }), 429

        _recent_sends.setdefault(user_id, deque()).append(now)
        _monthly_counts[user_id] = _monthly_counts.get(user_id, 0) + 1

    return None


def release_send(user_id):
    """Hand back a slot claimed by reserve_send, for a turn that never cost
    anything -- the request failed before reaching the model, or never got that
    far at all."""
    with _spend_lock:
        timestamps = _recent_sends.get(user_id)
        if timestamps:
            timestamps.pop()
            if not timestamps:
                del _recent_sends[user_id]
        if _monthly_counts.get(user_id, 0) > 0:
            _monthly_counts[user_id] -= 1


def rollback_turn(db, conversation_id, user_message_id, is_new_conversation):
    """Undo the database half of a chat turn that never produced a reply.

    The stored user message goes, so the frontend's retry can re-send the exact
    same text without duplicating it in the transcript; a brand-new conversation
    goes entirely, otherwise an empty titled chat is left in the sidebar.

    Rollback failures are logged rather than raised -- the caller is already on
    its way to returning an error, and a stale row is not worth replacing that
    error with a different one.
    """
    if user_message_id is not None:
        ok, error = chat_history.delete_message(db, user_message_id)
        if not ok:
            log.error("rollback of message %s failed: %s", user_message_id, error)

    if is_new_conversation and conversation_id is not None:
        ok, error = chat_history.delete_conversation(db, conversation_id)
        if not ok:
            log.error("rollback of conversation %s failed: %s",
                      conversation_id, error)


def get_caller():
# Every chat/history endpoint starts the same way: who is this?
# The frontend sends the access token it got from /login as
#     Authorization: Bearer <token>
# Returns (token, user_id), or (None, None) if the header is missing or the token
# is not valid -- the endpoint turns that into a 401.
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return (None, None)

    token = header[len("Bearer "):].strip()
    status = user_file.get_user_id(token)
    # status returns a tuple (true or false depending on whether the token is good,
    # the user id or an error message)
    if not status[0]:
        return (None, None)

    return (token, status[1])


def bearer_token():
# The expenses/budget/fees endpoints take the raw token straight through to
# Supabase rather than resolving a user id first.
    return request.headers.get("Authorization", "").removeprefix("Bearer ").strip()


def unauthorized():
    return jsonify({
        "success": False,
        "message": "Not logged in. Send 'Authorization: Bearer <access_token>'."
    }), 401

'''
@app.route("/test", methods=["POST"])
# /test is an endpoint in flask e.g https://5500/test and "/" is the deafult page e.g https://5500
# HTTP Methods (CRUD)
# GET    - Retrieve/read data from the server.
# POST   - Send data to create a new resource or perform an action.
# PUT    - Replace an existing resource with new data.
# PATCH  - Update specific fields of an existing resource.
# DELETE - Remove a resource from the server.
def signup(): # can only have 1 function per flask route
    data = request.get_json() # reads the JSON data sent in the HTTP request body and converts it into a Python dictionary.
    status = user_file.signup(data["name"], data["email"], data["password"])
    # status returns a tuple (true or false depending on suscessful login, error message)
    return jsonify ({
        "success": status[0],
        "message": status[1]
    })
'''

@app.route("/")
def home():
    return redirect("/html/home.html")

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() # turn what javascript sends to python dictionary
    status = user_file.login(data["email"], data["password"])
    # status returns a tuple (true or false depending on suscessful login, and on
    # success a dict with the tokens -- on failure just the error message)
    if not status[0]:
        return jsonify ({
            "success": False,
            "message": status[1]
        })

    # The frontend must save access_token and send it back as
    # "Authorization: Bearer <token>" on /chat and /conversations.
    return jsonify ({
        "success": True,
        "message": "No error",
        "access_token": status[1]["access_token"],
        "refresh_token": status[1]["refresh_token"],
        "user_id": status[1]["user_id"]
    })

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    status = user_file.signup(data["name"], data["email"], data["password"])
    # status returns a tuple (true or false depending on suscessful login, error message)
    return jsonify ({
        "success": status[0],
        "message": status[1]
    })

@app.route("/chat", methods=["POST"])
def chat():
    # The frontend no longer keeps the conversation in memory and no longer sends
    # it back to us. It sends ONE message plus the id of the chat it belongs to
    # (or null to start a new chat), and we load the history out of Supabase:
    #     {"conversation_id": "<uuid>" or null, "message": "..."}
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    # silent=True: malformed JSON gives us None instead of Flask's HTML error
    # page, so the frontend always gets our {"success": false} shape back.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Request body must be JSON."}), 400

    message = (data.get("message") or "").strip()
    conversation_id = data.get("conversation_id") # null on the first message of a new chat

    if not message:
        return jsonify({"success": False, "message": "Message is empty."}), 400

    # One paragraph only: newlines collapse to spaces, and the length cap stops
    # anyone pasting a document in -- we would pay to resend it on every one of
    # the next 30 turns while it sits in the replay window.
    message = " ".join(message.split())
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify({
            "success": False,
            "message": f"Please keep messages to one paragraph "
                       f"(under {MAX_MESSAGE_CHARS} characters)."
        }), 400

    # Claims the slot up front -- every early return below hands it back, since
    # none of them reached the model.
    limited = reserve_send(user_id)
    if limited:
        return limited

    # This client acts as the logged-in user, so the database's row level security
    # rules apply to every query below. Never use user_file.supabase_client here.
    db = user_file.client_for_token(token)

    is_new_conversation = not conversation_id

    if conversation_id:
        # Ownership check. db only sees this user's rows, so somebody else's chat
        # is indistinguishable from one that does not exist -- both are "not found".
        status = chat_history.get_conversation(db, conversation_id)
        if not status[0]:
            release_send(user_id)
            return jsonify({"success": False, "message": status[1]}), 404
        conversation = status[1]
    else:
        status = chat_history.create_conversation(db, user_id, message)
        if not status[0]:
            release_send(user_id)
            return jsonify({"success": False, "message": status[1]}), 500
        conversation = status[1]
        conversation_id = conversation["id"]

    status = chat_history.add_message(db, conversation_id, "user", message)
    if not status[0]:
        release_send(user_id)
        rollback_turn(db, conversation_id, None, is_new_conversation)
        return jsonify({"success": False, "message": status[1]}), 500
    user_message_id = status[1]["id"]

    # The model API is stateless, so we still replay the conversation -- but only the
    # recent window of it, straight from the database.
    status = chat_history.get_recent_messages(db, conversation_id)
    if not status[0]:
        release_send(user_id)
        rollback_turn(db, conversation_id, user_message_id, is_new_conversation)
        return jsonify({"success": False, "message": status[1]}), 500
    history = status[1]

    # Anything older than that window lives on as the rolling summary, which the
    # coach reads as context. It is None until the chat gets long (see chat_history).
    ok, payload, billed = kakeibo_ai.ask_coach(
        history, user_context=conversation.get("summary"))
    # ask_coach returns three parts: success, the reply text or an error message,
    # and whether the attempt actually cost money.
    if not ok:
        if not billed:
            release_send(user_id)
        rollback_turn(db, conversation_id, user_message_id, is_new_conversation)
        return jsonify({"success": False, "message": payload}), 502
    reply = payload

    status = chat_history.add_message(db, conversation_id, "assistant", reply)
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 500

    # Bookkeeping: float this chat to the top of the sidebar, and roll the old turns
    # up into the summary if it has got long. Neither changes the reply, so if they
    # fail we still hand the user what the coach said.
    chat_history.touch_conversation(db, conversation_id)
    chat_history.update_rolling_summary(db, conversation_id)

    return jsonify ({
        "success": True,
        "message": reply,
        "conversation_id": conversation_id
    })

@app.route("/conversations", methods=["GET"])
def conversations():
    # The chat sidebar: every chat this user has, newest first.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    db = user_file.client_for_token(token)
    status = chat_history.list_conversations(db, user_id)
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 500

    return jsonify ({
        "success": True,
        "conversations": status[1]
    })

@app.route("/conversations/<conversation_id>/messages", methods=["GET"])
def conversation_messages(conversation_id):
    # Reopening an old chat: the full transcript, so the frontend can redraw it.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    db = user_file.client_for_token(token)

    status = chat_history.get_conversation(db, conversation_id) # ownership check
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 404
    conversation = status[1]

    status = chat_history.get_messages(db, conversation_id)
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 500

    return jsonify ({
        "success": True,
        "conversation_id": conversation_id,
        "title": conversation.get("title"),
        "messages": status[1]
    })

@app.route("/health/ai", methods=["GET"])
def ai_health():
    # The frontend calls this on page load (no login needed): if ai_available
    # is false, it greys out the chat section and shows the "this service is
    # currently down" tooltip instead of letting the user type.
    return jsonify({"ai_available": kakeibo_ai.is_configured()})

@app.route("/health/companion", methods=["GET"])
def companion_health():
    # Same shape and purpose as /health/ai: no login needed, and the frontend
    # (see api.companionAvailable()) fails OPEN if this cannot be reached at
    # all -- an unknown answer should not hide the widget any more than it
    # would grey out the chat box.
    return jsonify({"companion_available": COMPANION_ENABLED})

@app.route("/logout")
def logout():
    user_file.logout()


# ---------------------------------------------------------------------------
# Expenses, budget, fees and purchase rules.
# ---------------------------------------------------------------------------
@app.route("/expenses", methods=["POST"])
def expense():
    print("expense routed")
    data = request.get_json()
    access_token = bearer_token()

    if(len(data) > 2):
        amount = data["amount"]
        purchase_date = data["purchase_date"]
        category = data["category"]
        print(access_token)
        status = expenses.report_expense(access_token, amount, purchase_date, category)
    else:
        amount = data["amount"]
        account = data["account"]
        status = expenses.report_fund(access_token, amount, account)

    return jsonify ({
        "success": status[0],
        "message": status[1]
    })

@app.route("/budget", methods=["GET"])
def get_budget():

    access_token = bearer_token()

    success, expenses_data = expenses.get_expenses(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": expenses_data
        })

    success, funds_data = expenses.get_funds(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": funds_data
        })

    income = 0

    if len(funds_data) > 0:
        income = float(funds_data[0]["amount"])

    summary = budget.calculate_budget(income, expenses_data)
    warnings = budget.evaluate_budget(summary)

    return jsonify({
        "success": True,
        "budget": summary,
        "warnings": warnings
    })


@app.route("/fees", methods=["GET"])
def get_fee_warnings():

    access_token = bearer_token()

    success, fees = fee_monitor.get_fees(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": fees
        })

    warnings = fee_monitor.check_fee_warnings(fees)

    return jsonify({
        "success": True,
        "warnings": warnings
    })

@app.route("/purchase-rules", methods=["POST"])
def evaluate_purchase():

    data = request.get_json()

    access_token = bearer_token()

    success, expenses_data = expenses.get_expenses(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": expenses_data
        })

    success, funds_data = expenses.get_funds(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": funds_data
        })

    income = float(funds_data[0]["amount"])

    result = purchase_rules.evaluate_purchase(
    income,
    expenses_data,
    float(data["amount"]),
    data["category"]
    )

    return jsonify({
    "success": True,
    "result": result
    })


# ---------------------------------------------------------------------------
# Weekly reflection -- the dashboard card.
#
# The question is generated once per user per week and then stored, so the model
# call happens on the first load of the week and every load after that is a plain
# database read. That is what keeps this feature off the spending guards above:
# there is no way to make it call the model more than once a week per user.
# ---------------------------------------------------------------------------
@app.route("/weekly-reflection", methods=["GET"])
def weekly_reflection():
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    ok, payload = reflections.get_current(token)
    if not ok:
        return jsonify({"success": False, "message": payload}), 500

    return jsonify({
        "success": True,
        "reflection": payload
    })


@app.route("/weekly-reflection", methods=["POST"])
def save_weekly_reflection():
    # Body: {"answer": "..."} -- answering again in the same week overwrites,
    # rather than stacking up rows the card could not show anyway.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Request body must be JSON."}), 400

    ok, payload = reflections.save_answer(token, data.get("answer"))
    if not ok:
        return jsonify({"success": False, "message": payload}), 400

    return jsonify({
        "success": True,
        "message": "Reflection saved.",
        "reflection": payload
    })


@app.route("/weekly-reflection/history", methods=["GET"])
def weekly_reflection_history():
    # Past weeks the user actually answered, newest first.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    ok, payload = reflections.list_history(token)
    if not ok:
        return jsonify({"success": False, "message": payload}), 500

    return jsonify({
        "success": True,
        "reflections": payload
    })


# ---------------------------------------------------------------------------
# Companion widget -- a cosmetic dashboard mascot. It only reflects data that
# expenses/budget/reflections already own, so there is no write path here that
# any other feature depends on; these two routes are the entire surface area.
# ---------------------------------------------------------------------------
@app.route("/companion", methods=["GET"])
def get_companion():
    if not COMPANION_ENABLED:
        return jsonify({"success": False, "message": "The companion is turned off."}), 404

    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    ok, payload = companion.get_state(token)
    if not ok:
        return jsonify({"success": False, "message": payload}), 500

    return jsonify({
        "success": True,
        "companion": payload
    })


@app.route("/companion/name", methods=["POST"])
def set_companion_name():
    # Body: {"name": "..."} -- purely cosmetic, so there is nothing to
    # validate here beyond what companion.set_name already checks.
    if not COMPANION_ENABLED:
        return jsonify({"success": False, "message": "The companion is turned off."}), 404

    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Request body must be JSON."}), 400

    ok, payload = companion.set_name(token, data.get("name"))
    if not ok:
        return jsonify({"success": False, "message": payload}), 400

    return jsonify({
        "success": True,
        "message": "Companion name saved.",
        "companion": payload
    })


# ---------------------------------------------------------------------------
# Generated documents: the monthly Kakeibo review and the onboarding profile.
#
# Both are stored as Markdown files in Supabase Storage (see reports.py), so a
# GET is normally a file read: storage bounds the GETs to one model call per
# month, and a read that fails is reported rather than treated as "not written
# yet", so a broken bucket cannot turn page loads into repeat generations.
#
# The POSTs have no such bound -- they exist to regenerate on demand -- so they
# go through the same reserve_send guard as /chat.
# ---------------------------------------------------------------------------
@app.route("/monthly-report", methods=["GET"])
def monthly_report():
    # ?month=YYYY-MM to look back at an earlier month; defaults to this one.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    ok, payload = reports.get_monthly(token, key=request.args.get("month"))
    if not ok:
        return jsonify({"success": False, "message": payload}), 400

    return jsonify({
        "success": True,
        "report": payload
    })


@app.route("/monthly-report", methods=["POST"])
def refresh_monthly_report():
    # Regenerate and overwrite. Separate from GET on purpose: rewriting the
    # month's review costs money, so it should never happen from a page load.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    data = request.get_json(silent=True) or {}

    # Claimed up front, like /chat: this route calls the model every time it is
    # reached, so nothing but the guard stands between a stuck retry loop and
    # the bill.
    #
    # No release_send on the failure path. get_monthly does not report whether a
    # failed run reached the model (only ask_coach does), and reserve_send's rule
    # is that the doubtful case counts -- costing a user one slot is the cheaper
    # mistake of the two.
    limited = reserve_send(user_id)
    if limited:
        return limited

    ok, payload = reports.get_monthly(token, key=data.get("month"), refresh=True)
    if not ok:
        return jsonify({"success": False, "message": payload}), 400

    return jsonify({
        "success": True,
        "report": payload
    })


@app.route("/profile", methods=["GET"])
def get_profile():
    # markdown is null when the user has not done the interview yet -- that is a
    # normal state, not an error, and the frontend shows the interview instead.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    ok, payload = reports.get_profile(token)
    if not ok:
        return jsonify({"success": False, "message": payload}), 500

    return jsonify({
        "success": True,
        "markdown": payload
    })


@app.route("/profile/interview", methods=["POST"])
def submit_interview():
    # Body: {"transcript": "..."} or {"transcript": ["Q: ...", "A: ...", ...]}
    # Re-running the interview replaces the stored profile.
    token, user_id = get_caller()
    if token is None:
        return unauthorized()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Request body must be JSON."}), 400

    # Same guard, and the same reasoning, as POST /monthly-report above.
    limited = reserve_send(user_id)
    if limited:
        return limited

    ok, payload = reports.save_profile(token, data.get("transcript"))
    if not ok:
        return jsonify({"success": False, "message": payload}), 400

    # The profile was written either way; `stored` says whether we managed to
    # keep it, and the message does not claim we did when we did not.
    return jsonify({
        "success": True,
        "message": "Profile saved." if payload["stored"] else
                   "Here is your profile, but it could not be saved -- you may "
                   "need to take the interview again later.",
        "markdown": payload["markdown"]
    })


if __name__ == "__main__":
    app.run(debug=True) #, port=5500)
