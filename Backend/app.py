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
import graphics


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

    if(len(data) > 2): # This is a very crude way to check if an expense or credit is being sent
        amount = data["amount"]
        purchase_date = data["purchase_date"]
        category = data["category"]
        print(access_token)
        status = expenses.report_expense(access_token, amount, purchase_date, category)
    else:
        print("debug 1")
        amount = data["amount"]
        account = data["account"]
        status = expenses.report_fund(access_token, amount, account)
        print("debug 2")

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

    success, funds_data = expenses.get_balance(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": funds_data
        })

    checking, savings = expenses._split_funds(funds_data) # I updated the funds table and made a split funds function
                                                          # to grab the information from each account easier
    income = checking


    #Updated this
    """income = 0

    if len(funds_data) > 0:
    income = float(funds_data[0]["amount"])"""

    # This user info from the _split_funds helper function since I updated
    summary = budget.calculate_budget(income, expenses_data)

    summary["Savings"] = savings #Regrabbing savings using _split_funds function

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

    success, funds_data = expenses.get_balance(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": funds_data
        })

    checking, _ = _split_funds(funds_data)
    income = checking

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


@app.route("/graphics", methods=["GET"])
def expenseGraph():
    # Get the graph DATA here. We will plot in expenses.js, just return the data JSONified.
    access_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    status = graphics.getGraphData(access_token)

    if status[0]:
        print("good")
        return jsonify({
            "success": True,
            "data": status[1]
        })
    return jsonify({
        "success": False,
        "message": status[1]
    })

if __name__ == "__main__":
    app.run(debug=True) #, port=5500)
