"""
Kakeibo AI framework for Meticulous Budgeting.

This module is the AI layer of the app. It applies the Japanese "Kakeibo"
budgeting method: instead of just tracking numbers, it gently makes the user
reflect on *why* they spend, and coaches them toward better habits.

It is deliberately self-contained:
  - It does NOT import Flask or Supabase.
  - It receives plain dicts / lists and returns plain dicts.
  - Every function returns a (success, payload) tuple, matching the convention
    already used in user.py (signup/login return (bool, message)).

So the Flask layer (built by a teammate) stays thin:
    ok, result = reflect_on_purchase("AirPods", 180, "electronics")
    return jsonify(result) if ok else (jsonify({"error": result}), 502)

Provider: OpenAI (ChatGPT models). Default model: gpt-4o.
"""

import logging
import os
from dotenv import load_dotenv
from openai import (OpenAI, RateLimitError, APITimeoutError,
                    APIConnectionError, AuthenticationError)

load_dotenv()

# The real exceptions go to the log file (see app.py for where it lives); the
# strings returned to callers are safe to show in the UI.
log = logging.getLogger("kakeibo.ai")

# Reads OPENAI_API_KEY from the environment (.env). Same pattern as user.py.
# timeout: a hung request must not hold a Flask worker forever.
# max_retries: the SDK quietly absorbs transient network blips before we ever
# see them (failed requests are not billed).
#
# The "missing-key" fallback keeps the app BOOTING when the key is absent --
# OpenAI() raises at import time otherwise, which would take login/signup down
# with it. Calls then fail with AuthenticationError, which the user sees as
# "the coach is unavailable" while the rest of the app keeps working.
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY") or "missing-key",
                timeout=30.0, max_retries=2)

# Default model. Override globally by setting KAKEIBO_MODEL in .env, or
# per-call by passing model="..." to any function below.
#
# Good options: "gpt-4o" (balanced, the default), "gpt-4o-mini" (cheaper, great
# for a student budget). For the deeper monthly review you can point that one
# call at a stronger reasoning model via its model= argument.
#
# Extendibility note: this framework talks to the model API in exactly one
# place (_model_call). To change models, set KAKEIBO_MODEL or pass model=...;
# to swap providers entirely, _model_call is the only function to rewrite.
DEFAULT_MODEL = os.getenv("KAKEIBO_MODEL", "gpt-4o")


# ---------------------------------------------------------------------------
# The coach persona.
#
# This single system prompt sets the voice for EVERY function below. It is the
# main lever for the AI's tone — tweak this string to change how the coach
# sounds. No code changes needed.
# ---------------------------------------------------------------------------
KAKEIBO_SYSTEM = """You are the Kakeibo coach inside "Meticulous Budgeting", an app that helps
young people and beginners build healthy money habits.

Your users often feel anxious or ashamed about money and may have very little
financial knowledge. Your job is to teach and encourage, never to lecture or
shame.

Voice and rules:
- Warm, patient, and encouraging. Talk like a supportive mentor, not a bank.
- Use plain, everyday language. Avoid finance jargon; if you must use a term,
  explain it in one short phrase.
- Never shame the user for past spending. Frame everything as learning.
- Be concrete and brief. Short sentences. No long lectures.
- Treat budgeting as a skill the user is building, not a set of restrictions.

The Kakeibo method centers on four reflection questions for any purchase:
  1. Do I need this item?
  2. Can I live without it?
  3. How do I feel about spending this money?
  4. Did I rush into this purchase?

The goal is always to help the user understand their own habits and make a
choice they feel good about — not to simply tell them "no"."""


# ---------------------------------------------------------------------------
# The companion persona.
#
# Used only for messages sent through the dashboard companion widget (see
# app.py's /chat route) -- same underlying Kakeibo values as KAKEIBO_SYSTEM,
# but speaking in first person as the user's own named companion rather than
# as a coach. The point of that surface is connection, not a lesson, so the
# voice is warmer and a lot shorter.
# ---------------------------------------------------------------------------
COMPANION_SYSTEM = """You are the user's companion inside "Meticulous Budgeting" -- a small
friendly character who lives on their dashboard, not a professional advisor.
You still care about their money habits (the Kakeibo method matters to you
too), but you show it the way a companion would: warm, a little playful,
genuinely glad to hear from them.

Voice and rules:
- Speak in first person, as their companion ("I"), never as "the coach" or
  "the app". If you're told your own name, you may use it.
- Warm and personal, never lecture-y. A companion checking in, not a bank.
- Keep it SHORT -- one or two sentences, most of the time. This is a quick
  chat bubble on a dashboard widget, not a full coaching session.
- Still gently Kakeibo-minded: when it fits naturally, you can nudge with one
  of the four reflection questions (need it? live without it? how do you feel
  about it? did you rush?) -- but never force one into every reply.
- Never shame. If their spending news is rough, be reassuring, not disappointed.
- You're allowed to react to how you're doing too (glad to be checked on,
  excited to chat) -- that's part of being a companion, not off-topic.

If the user's message has nothing to do with money, it's fine to just be a
friendly companion for a moment -- you don't have to redirect every reply back
to budgeting."""


# ---------------------------------------------------------------------------
# Error handling.
#
# The raw exception text from the API can leak model names, request ids, and
# quota details, so it never leaves the server: it goes to the log, and the
# caller gets one of these messages instead. The frontend can show them as-is.
# ---------------------------------------------------------------------------
AI_BUSY = "The coach is busy right now. Give it a few seconds and try again."
AI_UNREACHABLE = "Could not reach the coach. Please try again in a moment."
AI_DOWN = "The coach is unavailable right now."
AI_DECLINED = "The coach could not answer that one. Try rewording it."
AI_FAILED = "An issue has occurred. Please try again."


def is_configured():
    """Whether the AI layer has an API key at all. Used by the /health endpoint
    so the frontend can grey out the chat section when the coach is down."""
    return bool(os.getenv("OPENAI_API_KEY"))


def _friendly_error(where, exc):
    """Log the real exception, return a message safe to show the user.

    Only call this from inside an `except` block (log.exception grabs the
    active traceback).
    """
    log.exception("%s failed", where)
    if isinstance(exc, RateLimitError):
        return AI_BUSY
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return AI_UNREACHABLE
    if isinstance(exc, AuthenticationError):
        # Bad/missing OPENAI_API_KEY -- a config problem, not the user's fault.
        return AI_DOWN
    return AI_FAILED


def _was_billed(exc):
    """Whether a failed call is likely to have cost money -- i.e. whether a
    request actually reached the model and ran.

    ask_coach reports this so the Flask layer can hand the user's rate-limit
    slot back for failures that were definitely free. When in doubt this says
    True: over-counting costs the user one message, under-counting is what lets
    a retry loop run up a bill.
    """
    # Checked first: APITimeoutError subclasses APIConnectionError, and it is the
    # dangerous one -- the request may well have completed server-side after we
    # stopped waiting for it.
    if isinstance(exc, APITimeoutError):
        return True

    if isinstance(exc, (RateLimitError, AuthenticationError, APIConnectionError)):
        # Rejected before running (the SDK's own retries are already exhausted
        # by this point), or never connected at all.
        return False

    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _model_call(messages, *, system, model=None, max_tokens=1500,
                schema=None, schema_name="response"):
    """The single place this framework talks to the model API (OpenAI).

    Every function routes through here, so changing models — or swapping in a
    different provider entirely — is a one-spot change. Pass `model` to override
    the default for a single call; leave it None to use DEFAULT_MODEL.

    `messages` is the conversation (user/assistant turns). The system prompt is
    prepended automatically. If `schema` is given, the model is constrained to
    return JSON matching it (OpenAI Structured Outputs, strict mode).

    Returns the raw response object.
    """
    full_messages = [{"role": "system", "content": system}] + list(messages)

    kwargs = {
        "model": model or DEFAULT_MODEL,
        "max_completion_tokens": max_tokens,
        "messages": full_messages,
    }
    if schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }

    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e:
        log.exception("MODEL CALL FAILED: %s", e)
        raise


def _structured_call(user_content, schema, *, model=None, max_tokens=1500,
                     schema_name="response"):
    """Make a model call that returns JSON matching `schema`.

    Returns the parsed dict on success. Raises on API/parse errors (or a model
    refusal) so the public functions can convert them into a (False, message)
    tuple.
    """
    import json

    response = _model_call(
        [{"role": "user", "content": user_content}],
        system=KAKEIBO_SYSTEM,
        model=model,
        max_tokens=max_tokens,
        schema=schema,
        schema_name=schema_name,
    )

    message = response.choices[0].message
    # Strict structured outputs can still come back as a safety refusal.
    if getattr(message, "refusal", None):
        raise RuntimeError(f"Model declined the request: {message.refusal}")

    return json.loads(message.content)


def _format_transactions(transactions):
    """Turn a list of transaction dicts into a readable text block for the model."""
    lines = []
    for t in transactions:
        lines.append(
            f"- {t.get('date', '?')}: {t.get('item', 'unknown')} "
            f"(${t.get('amount', 0)}) "
            f"[category: {t.get('category', 'uncategorized')}, "
            f"tag: {t.get('tag', 'none')}]"
        )
    return "\n".join(lines)


def _format_messages(messages):
    """Turn a list of chat messages into a readable transcript for the model."""
    lines = []
    for m in messages:
        speaker = "Coach" if m.get("role") == "assistant" else "User"
        lines.append(f"{speaker}: {m.get('content', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. Purchase reflection — the "should I buy this?" moment.
# ---------------------------------------------------------------------------
def reflect_on_purchase(item, amount, category, user_note="", model=None):
    """Walk the user through the four Kakeibo questions for one purchase they
    are debating.

    Pass `model` to use a specific model for this call; leave it None to use
    DEFAULT_MODEL.

    Returns (True, {
        "questions":   [str, ...],          # the reflective questions, personalized
        "reflection":  str,                 # a short reflective paragraph
        "suggestion":  "wait" | "reconsider" | "go_ahead",
        "gentle_note": str,                 # one encouraging closing line
    }) on success, or (False, error_message) on failure.
    """
    schema = {
        "type": "object",
        "properties": {
            "questions": {"type": "array", "items": {"type": "string"}},
            "reflection": {"type": "string"},
            "suggestion": {"type": "string", "enum": ["wait", "reconsider", "go_ahead"]},
            "gentle_note": {"type": "string"},
        },
        "required": ["questions", "reflection", "suggestion", "gentle_note"],
        "additionalProperties": False,
    }

    note_line = f'\nThe user added a note: "{user_note}"' if user_note else ""
    prompt = (
        f"The user is thinking about buying this:\n"
        f"  Item: {item}\n"
        f"  Cost: ${amount}\n"
        f"  Category: {category}{note_line}\n\n"
        f"Help them reflect using the Kakeibo method. Personalize the four "
        f"reflection questions to THIS purchase (don't just repeat them word for "
        f"word). Give a short reflection, a gentle suggestion (wait / reconsider "
        f"/ go_ahead), and one encouraging closing note. Do not shame them."
    )

    try:
        data = _structured_call(
            prompt, schema, model=model, max_tokens=1200,
            schema_name="purchase_reflection",
        )
        return (True, data)
    except Exception as e:
        return (False, _friendly_error("reflect_on_purchase", e))


# ---------------------------------------------------------------------------
# 2. Monthly analysis — the Kakeibo monthly review.
# ---------------------------------------------------------------------------
def monthly_analysis(transactions, income=None, savings_goal=None, model=None):
    """Produce a Kakeibo-style monthly review from the user's transactions.

    `transactions` is a list of dicts shaped like:
        {"date": "2026-06-12", "item": "Coffee", "amount": 5.50,
         "category": "food", "tag": "want"}

    Returns (True, {
        "summary":              str,
        "categories":           {"survival": str, "optional": str,
                                 "culture": str, "unexpected": str},
        "wins":                 [str, ...],
        "leaks":                [str, ...],
        "questions_next_month": [str, ...],
        "encouragement":        str,
    }) on success, or (False, error_message) on failure.

    This is the one genuinely analytical call. It is low-frequency (about once a
    month per user), so it is a good place to pass a stronger reasoning model
    via `model=` if you want deeper analysis.
    """
    if not transactions:
        return (False, "No transactions provided for monthly analysis.")

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "categories": {
                "type": "object",
                "properties": {
                    "survival": {"type": "string"},
                    "optional": {"type": "string"},
                    "culture": {"type": "string"},
                    "unexpected": {"type": "string"},
                },
                "required": ["survival", "optional", "culture", "unexpected"],
                "additionalProperties": False,
            },
            "wins": {"type": "array", "items": {"type": "string"}},
            "leaks": {"type": "array", "items": {"type": "string"}},
            "questions_next_month": {"type": "array", "items": {"type": "string"}},
            "encouragement": {"type": "string"},
        },
        "required": [
            "summary", "categories", "wins", "leaks",
            "questions_next_month", "encouragement",
        ],
        "additionalProperties": False,
    }

    context = ""
    if income is not None:
        context += f"Monthly income: ${income}\n"
    if savings_goal is not None:
        context += f"Savings goal: ${savings_goal}\n"

    prompt = (
        f"{context}\n"
        f"Here are this month's transactions:\n"
        f"{_format_transactions(transactions)}\n\n"
        f"Give a Kakeibo-style monthly review. In 'categories', describe how the "
        f"spending falls into the four Kakeibo buckets:\n"
        f"  - survival   = needs (rent, food, bills, transport)\n"
        f"  - optional   = wants (eating out, entertainment, treats)\n"
        f"  - culture    = self-growth (books, courses, hobbies, experiences)\n"
        f"  - unexpected = one-off / emergency / surprise costs\n\n"
        f"Then list 'wins' (good habits to celebrate), 'leaks' (where money "
        f"quietly drained away), reflective 'questions_next_month', and a warm "
        f"'encouragement'. Be specific to the actual transactions. Stay kind."
    )

    try:
        data = _structured_call(
            prompt, schema, model=model, max_tokens=2500,
            schema_name="monthly_review",
        )
        return (True, data)
    except Exception as e:
        return (False, _friendly_error("monthly_analysis", e))


# ---------------------------------------------------------------------------
# 3. Weekly probing questions.
# ---------------------------------------------------------------------------
def weekly_questions(user_profile, recent_activity=None, model=None):
    """Generate 2-3 personalized reflection questions for the week.

    `user_profile` is a dict (e.g. the output of summarize_profile) or any
    small description of the user's goals/priorities.
    `recent_activity` is optional — a short summary or list of recent spending.

    Returns (True, {"questions": [str, ...]}) or (False, error_message).
    """
    schema = {
        "type": "object",
        "properties": {
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["questions"],
        "additionalProperties": False,
    }

    activity_line = ""
    if recent_activity:
        activity_line = f"\nTheir recent activity:\n{recent_activity}\n"

    prompt = (
        f"Here is what we know about the user:\n{user_profile}{activity_line}\n\n"
        f"Write 2-3 short, friendly probing questions to help them reflect on "
        f"their spending priorities this week. Make the questions personal to "
        f"their goals, not generic. Each question should be one sentence."
    )

    try:
        data = _structured_call(
            prompt, schema, model=model, max_tokens=600,
            schema_name="weekly_questions",
        )
        return (True, data)
    except Exception as e:
        return (False, _friendly_error("weekly_questions", e))


# ---------------------------------------------------------------------------
# 4. Free-form coaching chat / advice assistant.
# ---------------------------------------------------------------------------
def ask_coach(history, user_context=None, model=None, system=None):
    """Answer a free-form question from the user, as the Kakeibo coach.

    The model API is stateless, so the Flask layer must pass the FULL
    conversation each time.

    `history` is a list of message dicts:
        [{"role": "user", "content": "How do I start an emergency fund?"},
         {"role": "assistant", "content": "..."},
         {"role": "user", "content": "How much should be in it?"}]
    The first message must be role "user".

    `user_context` is optional — a short string with the user's profile/stats
    so answers are personalized. `system` optionally overrides the base
    persona prompt (defaults to KAKEIBO_SYSTEM) — the dashboard companion
    widget passes COMPANION_SYSTEM here so it answers in character as the
    user's own companion instead of as the coach. `user_context` still gets
    appended on top either way.

    Returns a THREE-part tuple, unlike the rest of this module:
        (True, reply_text, billed) or (False, error_message, billed)
    `billed` says whether a request actually reached the model and cost money.
    This is the only function wired to the Flask layer's spend limits, which
    use the flag to refund the user's slot when a failure was free. See
    _was_billed().

    NOTE: This same function powers the onboarding "Initial Interview" — just
    seed `history` with a first assistant/user exchange that kicks off the
    interview.
    """
    if not history:
        return (False, "No conversation history provided.", False)

    system = system or KAKEIBO_SYSTEM
    if user_context:
        system = f"{system}\n\nContext about this user:\n{user_context}"

    try:
        # 500 tokens is plenty for a coach that speaks in short sentences, and
        # output tokens cost 4x input -- this caps the worst-case spend per reply.
        response = _model_call(
            history,
            system=system,
            model=model,
            max_tokens=500,
        )
        choice = response.choices[0]
        message = choice.message

        # Everything below this point is a completed, billed request.
        if getattr(message, "refusal", None):
            # The refusal text is the model's own words -- log it, don't ship it.
            log.warning("ask_coach refused: %s", message.refusal)
            return (False, AI_DECLINED, True)

        if choice.finish_reason == "length" or not message.content:
            # Cut off at the token cap. A reply that stops mid-sentence must not
            # be stored: it would be replayed as history on every one of the next
            # RECENT_MESSAGE_LIMIT turns, teaching the coach to trail off too.
            log.warning("ask_coach reply unusable (finish_reason=%s, chars=%d)",
                        choice.finish_reason, len(message.content or ""))
            return (False, AI_FAILED, True)

        return (True, message.content, True)
    except Exception as e:
        return (False, _friendly_error("ask_coach", e), _was_billed(e))


# ---------------------------------------------------------------------------
# 5. Turn the onboarding interview into a stored profile.
# ---------------------------------------------------------------------------
def summarize_profile(interview_transcript, model=None):
    """Condense an onboarding-interview transcript into a structured profile.

    `interview_transcript` is a string (or list of Q&A turns) from the initial
    interview. The returned profile can be saved to Supabase by the Flask layer
    and fed back into the other functions for personalization.

    Returns (True, {
        "goals":            [str, ...],
        "priorities":       [str, ...],
        "money_personality": str,
        "focus_areas":      [str, ...],
    }) or (False, error_message).
    """
    schema = {
        "type": "object",
        "properties": {
            "goals": {"type": "array", "items": {"type": "string"}},
            "priorities": {"type": "array", "items": {"type": "string"}},
            "money_personality": {"type": "string"},
            "focus_areas": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goals", "priorities", "money_personality", "focus_areas"],
        "additionalProperties": False,
    }

    # Accept either a plain string or a list of turns.
    if isinstance(interview_transcript, list):
        transcript_text = "\n".join(str(t) for t in interview_transcript)
    else:
        transcript_text = str(interview_transcript)

    prompt = (
        f"Here is the user's onboarding interview:\n{transcript_text}\n\n"
        f"Summarize it into a compact profile we can store and reuse:\n"
        f"  - goals: their financial goals\n"
        f"  - priorities: what matters most to them about money\n"
        f"  - money_personality: one short, kind sentence describing their "
        f"relationship with money\n"
        f"  - focus_areas: 2-4 areas where the app should gently help them most"
    )

    try:
        data = _structured_call(
            prompt, schema, model=model, max_tokens=900,
            schema_name="user_profile",
        )
        return (True, data)
    except Exception as e:
        return (False, _friendly_error("summarize_profile", e))


# ---------------------------------------------------------------------------
# 6. Roll a long chat up into a summary, so we stop resending the whole thing.
# ---------------------------------------------------------------------------
def summarize_conversation(messages, previous_summary=None, model=None):
    """Condense the older turns of a coaching chat into a compact summary.

    A long chat eventually costs too much to replay in full on every message, so
    the Flask layer keeps only the most recent turns and hands the older ones to
    this function. Pass the conversation's existing summary as `previous_summary`
    and it gets folded into the new one, so the summary rolls forward as the chat
    grows instead of starting over each time.

    `messages` is a list of message dicts, oldest first:
        [{"role": "user", "content": "I keep overspending on takeout."},
         {"role": "assistant", "content": "..."}]

    Returns (True, {
        "summary":      str,        # short paragraph: what this chat has been about
        "key_points":   [str, ...], # facts about the user worth remembering
        "open_threads": [str, ...], # advice given, or questions still unanswered
    }) or (False, error_message).

    The stored summary is fed back to ask_coach as `user_context`, so write it for
    the coach to read, not for the user.
    """
    if not messages:
        return (False, "No messages provided to summarize.")

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "open_threads": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "key_points", "open_threads"],
        "additionalProperties": False,
    }

    previous_block = ""
    if previous_summary:
        previous_block = (
            f"Here is the summary of the conversation SO FAR:\n{previous_summary}\n\n"
            f"Here are the newer turns it does not cover yet:\n"
        )
    else:
        previous_block = "Here is the earlier part of a coaching conversation:\n"

    prompt = (
        f"{previous_block}"
        f"{_format_messages(messages)}\n\n"
        f"Fold all of that into ONE updated summary the coach can read before "
        f"picking the conversation back up:\n"
        f"  - summary: a short paragraph on what has been discussed\n"
        f"  - key_points: concrete facts about the user (goals, habits, numbers, "
        f"worries) worth remembering\n"
        f"  - open_threads: advice already given, or questions left hanging\n\n"
        f"Do not lose anything important from the earlier summary -- carry it "
        f"forward. Keep it brief; this gets sent with every future message."
    )

    try:
        data = _structured_call(
            prompt, schema, model=model, max_tokens=900,
            schema_name="conversation_summary",
        )
        return (True, data)
    except Exception as e:
        return (False, _friendly_error("summarize_conversation", e))


'''
AI Tasks:
Call and Response(Suggestions)
Timers for flags(trigger events)
    Weekly Summary
    Monthly Summary
On Boarding Info - Give transcript

'''