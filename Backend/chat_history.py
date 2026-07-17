"""
Storage for the coach's chat history (Supabase).

kakeibo_ai.py deliberately knows nothing about Supabase, and app.py is meant to
stay a thin Flask layer, so all the "save this chat / load it back" work lives
here in the middle.

The tables are in migrations/001_chat_history.sql (conversations + messages).

Every function takes a `db` client as its first argument -- the per-request,
per-user client from user.client_for_token(). That client carries the caller's
access token, so Row Level Security does the ownership check inside the database:
another user's rows are not merely hidden from our queries, they do not exist as
far as this client is concerned. Never pass user.supabase_client in here.

Like user.py and kakeibo_ai.py, every function returns a (success, payload) tuple.
"""

from datetime import datetime, timezone

import kakeibo_ai


# How many recent messages we replay to the model on each /chat call. Everything
# older than this is represented by the conversation's rolling summary instead.
RECENT_MESSAGE_LIMIT = 30

# A chat only starts getting summarized once it is longer than this.
SUMMARY_THRESHOLD = 40

# ...and after that we only pay for a summarization call once this many un-summarized
# old messages have piled up, so we are not calling the model on every single turn.
# (THRESHOLD = RECENT_MESSAGE_LIMIT + SUMMARY_BATCH is the natural setting.)
SUMMARY_BATCH = 10

# Conversations are titled with the opening message, trimmed to this many chars.
TITLE_LENGTH = 60


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
def create_conversation(db, user_id, first_message):
    """Start a new chat thread, titled after the user's opening message.

    Returns (True, {"id": ..., "title": ..., "summary": None, ...}) or
    (False, error_message).
    """
    title = first_message.strip()[:TITLE_LENGTH]

    try:
        response = db.table("conversations").insert({
            "user_id": user_id,
            "title": title,
        }).execute()

        if not response.data:
            return (False, "Could not create the conversation.")

        return (True, response.data[0])
    except Exception as e:
        return (False, f"Could not create the conversation: {e}")


def get_conversation(db, conversation_id):
    """Fetch one conversation row.

    This doubles as the ownership check: `db` is scoped to the logged-in user, so
    somebody else's conversation comes back empty and we report it as not found.

    Returns (True, conversation_row) or (False, error_message).
    """
    try:
        response = (db.table("conversations")
                      .select("*")
                      .eq("id", conversation_id)
                      .limit(1)
                      .execute())

        if not response.data:
            return (False, "Conversation not found.")

        return (True, response.data[0])
    except Exception as e:
        return (False, f"Could not load the conversation: {e}")


def list_conversations(db, user_id):
    """List the user's chats for the sidebar, newest activity first.

    Returns (True, [{"id": ..., "title": ..., "updated_at": ...}, ...]) or
    (False, error_message).
    """
    try:
        response = (db.table("conversations")
                      .select("id, title, updated_at")
                      .eq("user_id", user_id)
                      .order("updated_at", desc=True)
                      .execute())

        return (True, response.data or [])
    except Exception as e:
        return (False, f"Could not list conversations: {e}")


def touch_conversation(db, conversation_id):
    """Bump updated_at so this chat floats to the top of the sidebar.

    Postgres will not do this for us -- there is no trigger on the table -- so the
    Flask layer calls it after each exchange.

    Returns (True, None) or (False, error_message).
    """
    try:
        # A bare "now()" here would be sent to Postgres as the literal string
        # "now()", not the function, so send an actual timestamp instead.
        db.table("conversations").update({
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", conversation_id).execute()

        return (True, None)
    except Exception as e:
        return (False, f"Could not update the conversation: {e}")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def add_message(db, conversation_id, role, content):
    """Append one message ("user" or "assistant") to a conversation.

    Returns (True, message_row) or (False, error_message).
    """
    try:
        response = db.table("messages").insert({
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
        }).execute()

        if not response.data:
            return (False, "Could not save the message.")

        return (True, response.data[0])
    except Exception as e:
        return (False, f"Could not save the message: {e}")


def get_recent_messages(db, conversation_id, limit=RECENT_MESSAGE_LIMIT):
    """Fetch the last `limit` messages, oldest first -- the window we send to the model.

    Returns (True, [{"role": ..., "content": ...}, ...]) or (False, error_message).
    """
    try:
        # Newest-first + limit gets us the tail of the chat; flip it back to
        # chronological order, which is what ask_coach expects.
        response = (db.table("messages")
                      .select("role, content")
                      .eq("conversation_id", conversation_id)
                      .order("created_at", desc=True)
                      .order("id", desc=True)
                      .limit(limit)
                      .execute())

        messages = list(reversed(response.data or []))

        # The window can start mid-exchange, on the coach's half of it. ask_coach
        # wants the first message to be the user's, so drop that dangling reply.
        if messages and messages[0]["role"] != "user":
            messages = messages[1:]

        return (True, messages)
    except Exception as e:
        return (False, f"Could not load the conversation: {e}")


def get_messages(db, conversation_id):
    """Fetch the whole transcript, oldest first -- for restoring a chat in the UI.

    Returns (True, [{"id": ..., "role": ..., "content": ..., "created_at": ...}, ...])
    or (False, error_message).
    """
    try:
        response = (db.table("messages")
                      .select("id, role, content, created_at")
                      .eq("conversation_id", conversation_id)
                      .order("created_at")
                      .order("id")
                      .execute())

        return (True, response.data or [])
    except Exception as e:
        return (False, f"Could not load the messages: {e}")


def count_messages(db, conversation_id):
    """How many messages this conversation has. Cheap: asks Postgres to count.

    Returns (True, count) or (False, error_message).
    """
    try:
        response = (db.table("messages")
                      .select("id", count="exact")
                      .eq("conversation_id", conversation_id)
                      .limit(1)
                      .execute())

        return (True, response.count or 0)
    except Exception as e:
        return (False, f"Could not count the messages: {e}")


# ---------------------------------------------------------------------------
# The rolling summary.
#
# Without this, a long chat means resending the entire transcript to the model on
# every single message -- slower and more expensive every turn. Instead, once a
# chat passes SUMMARY_THRESHOLD, the turns that have fallen out of the recent
# window get folded into conversations.summary, and /chat sends
# "summary + last RECENT_MESSAGE_LIMIT messages" from then on.
# ---------------------------------------------------------------------------
def _render_summary(payload):
    """Flatten summarize_conversation's dict into the text we store and later feed
    to ask_coach as user_context."""
    lines = [f"Summary of the earlier part of this conversation:\n{payload['summary']}"]

    if payload.get("key_points"):
        lines.append("\nWhat we know about the user:")
        lines += [f"- {point}" for point in payload["key_points"]]

    if payload.get("open_threads"):
        lines.append("\nStill open:")
        lines += [f"- {thread}" for thread in payload["open_threads"]]

    return "\n".join(lines)


def update_rolling_summary(db, conversation_id):
    """Fold this chat's old turns into conversations.summary, if it has grown enough.

    Called after every exchange. It is a no-op for short chats, which is most of
    them, so it is cheap to call unconditionally.

    conversations.summarized_through remembers the last message already folded in,
    so each summarization call only pays for the messages added since the last one
    (the previous summary carries the rest forward).

    Returns (True, summary_text) if a new summary was written, (True, None) if the
    chat was still too short to need one, or (False, error_message).
    """
    ok, count = count_messages(db, conversation_id)
    if not ok:
        return (False, count)

    if count < SUMMARY_THRESHOLD:
        return (True, None)

    ok, conversation = get_conversation(db, conversation_id)
    if not ok:
        return (False, conversation)

    try:
        # Everything outside the recent window is fair game to summarize.
        response = (db.table("messages")
                      .select("id, role, content")
                      .eq("conversation_id", conversation_id)
                      .order("created_at")
                      .order("id")
                      .limit(count - RECENT_MESSAGE_LIMIT)
                      .execute())
        older = response.data or []
    except Exception as e:
        return (False, f"Could not load the older messages: {e}")

    # ...minus whatever the existing summary already covers.
    summarized_through = conversation.get("summarized_through") or 0
    fresh = [m for m in older if m["id"] > summarized_through]

    # Wait until a batch has built up rather than re-summarizing every turn.
    if len(fresh) < SUMMARY_BATCH:
        return (True, None)

    ok, payload = kakeibo_ai.summarize_conversation(
        [{"role": m["role"], "content": m["content"]} for m in fresh],
        previous_summary=conversation.get("summary"),
    )
    if not ok:
        return (False, payload)

    summary_text = _render_summary(payload)

    try:
        db.table("conversations").update({
            "summary": summary_text,
            "summarized_through": fresh[-1]["id"],
        }).eq("id", conversation_id).execute()

        return (True, summary_text)
    except Exception as e:
        return (False, f"Could not save the conversation summary: {e}")
