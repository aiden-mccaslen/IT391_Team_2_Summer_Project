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
