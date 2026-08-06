# route logout back to signup (and add the "you have logged out popup")
from  flask import request, Flask, jsonify, url_for, redirect
from flask_cors import CORS
import user as user_file
import kakeibo_ai
import chat_history
import expenses

app = Flask(__name__, static_folder="../Frontend", static_url_path="")
CORS(app) # change this to restrict endpoints later

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

if __name__ == "__main__":
    app.run(debug=True) #, port=5500)
