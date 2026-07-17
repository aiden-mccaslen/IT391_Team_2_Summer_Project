# route logout back to signup (and add the "you have logged out popup")

from  flask import request, Flask, jsonify, url_for, redirect
from flask_cors import CORS
import user as user_file
import kakeibo_ai
import chat_history


app = Flask(__name__)
CORS(app) # change this to restrict endpoints later


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
    return login.html

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

    data = request.get_json() # turn what javascript sends to python dictionary
    message = (data.get("message") or "").strip()
    conversation_id = data.get("conversation_id") # null on the first message of a new chat

    if not message:
        return jsonify({"success": False, "message": "Message is empty."}), 400

    # This client acts as the logged-in user, so the database's row level security
    # rules apply to every query below. Never use user_file.supabase_client here.
    db = user_file.client_for_token(token)

    if conversation_id:
        # Ownership check. db only sees this user's rows, so somebody else's chat
        # is indistinguishable from one that does not exist -- both are "not found".
        status = chat_history.get_conversation(db, conversation_id)
        if not status[0]:
            return jsonify({"success": False, "message": status[1]}), 404
        conversation = status[1]
    else:
        status = chat_history.create_conversation(db, user_id, message)
        if not status[0]:
            return jsonify({"success": False, "message": status[1]}), 500
        conversation = status[1]
        conversation_id = conversation["id"]

    status = chat_history.add_message(db, conversation_id, "user", message)
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 500

    # The model API is stateless, so we still replay the conversation -- but only the
    # recent window of it, straight from the database.
    status = chat_history.get_recent_messages(db, conversation_id)
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 500
    history = status[1]

    # Anything older than that window lives on as the rolling summary, which the
    # coach reads as context. It is None until the chat gets long (see chat_history).
    status = kakeibo_ai.ask_coach(history, user_context=conversation.get("summary"))
    # status returns a tuple (true or false depending on success, reply text or error message)
    if not status[0]:
        return jsonify({"success": False, "message": status[1]}), 502
    reply = status[1]

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

@app.route("/logout")
def logout():
    user_file.logout()

if __name__ == "__main__":
    app.run()
