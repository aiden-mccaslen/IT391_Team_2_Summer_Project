"""
The dashboard's weekly reflection card (Supabase + the coach).

One question per user per week, stored with whatever the user writes back. The
table is in migrations/003_weekly_reflections.sql.

Like expenses.py, every function here takes the caller's access token and builds
its own per-user client through user.caller_client(), so Row Level Security does
the ownership check inside the database rather than in the Flask layer.

Every function returns a (success, payload) tuple, same as the rest of the backend.
"""

import logging
from datetime import datetime, timedelta, timezone

import budget
import expenses
import kakeibo_ai
import reports
import user as user_file


log = logging.getLogger("kakeibo.reflections")

# The card is a single line of text, not a journal page.
MAX_ANSWER_CHARS = 1000

# How many past weeks the history endpoint hands back.
HISTORY_LIMIT = 8

# The columns the card needs, in one place so every read of the table agrees.
FIELDS = "id, week_start, question, answer, answered_at"

# Used when the coach is switched off or its call fails. The week number picks
# one, so the card still changes week to week instead of asking the same thing
# forever -- and a user who never has AI available still gets the feature.
FALLBACK_QUESTIONS = [
    "What purchase brought you the most joy this week, and why?",
    "Was there anything you bought this week that you already regret?",
    "Which spending habit would you most like to change next week?",
    "What did you choose NOT to buy this week, and how did that feel?",
    "Where did your money go without you really deciding it should?",
]


def week_start(today=None):
    """The Monday of the given week (UTC), which is how a week is identified in
    the table. Defaults to the current week."""
    today = today or datetime.now(timezone.utc).date()
    return today - timedelta(days=today.weekday())


def _fallback_question(monday):
    """The question to use when the coach cannot write one. Keyed on the week so
    the card still changes week to week."""
    return FALLBACK_QUESTIONS[monday.isocalendar()[1] % len(FALLBACK_QUESTIONS)]


def _recent_context(access_token, caller=None):
    """Build the two short strings the coach needs to personalize a question:
    what the user's budget looks like, and what they spent in the last 7 days.

    Best effort by design -- ANY failure in here returns what we have so far. A
    generic question is a much better outcome than no card at all, so nothing
    below is allowed to propagate out and turn the endpoint into a 500.

    `caller` is an already-resolved (uuid, client) pair, so the profile read
    shares this request's token check. The two expenses reads still do their own
    -- adding the parameter to expenses.py would put this branch's changes in a
    file the rest of the team is working in.
    """
    profile_lines = []
    activity_lines = []

    try:
        # What the user told us in the onboarding interview, if they did it. This
        # is the part that makes the question about their goals rather than about
        # the numbers alone -- everything below is derived from spending, which
        # says what they did but nothing about what they were trying to do.
        ok, profile_md = reports.get_profile(access_token, caller=caller)
        if ok and profile_md:
            profile_lines.append(profile_md.strip())

        ok, expenses_data = expenses.get_expenses(access_token)
        if not ok:
            log.info("reflection context: could not read expenses: %s", expenses_data)
            expenses_data = []

        ok, funds_data = expenses.get_balance(access_token)
        if not ok:
            log.info("reflection context: could not read funds: %s", funds_data)
            funds_data = []

        income = 0.0
        if funds_data:
            try:
                income = float(funds_data[0]["amount"])
            except (TypeError, ValueError, KeyError):
                income = 0.0

        if income > 0:
            profile_lines.append(f"Monthly income: ${income:,.2f}")

        summary = budget.calculate_budget(income, expenses_data)
        profile_lines.append(
            f"Spending so far -- needs ${summary['Need']:,.2f} "
            f"({summary['NeedPercent']}%), wants ${summary['Want']:,.2f} "
            f"({summary['WantPercent']}%), savings ${summary['Savings']:,.2f} "
            f"({summary['SavingsPercent']}%). They are following the 50/30/20 rule."
        )

        warnings = budget.evaluate_budget(summary)
        if warnings:
            profile_lines.append("Current warnings: " + " ".join(warnings))

        # Only the last 7 days count as "this week's activity". purchase_date
        # comes back from Postgres as a "YYYY-MM-DD" string, so a string compare
        # is an ordering compare -- but anything unexpected is skipped rather
        # than crashing the card. UTC to match week_start(), so the cutoff and
        # the week it belongs to cannot disagree on a server that is not on UTC.
        today = datetime.now(timezone.utc).date()
        cutoff = (today - timedelta(days=7)).isoformat()
        for expense in expenses_data:
            purchase_date = expense.get("purchase_date")
            if not isinstance(purchase_date, str) or purchase_date < cutoff:
                continue
            activity_lines.append(
                f"- {purchase_date}: ${expense.get('amount')} on {expense.get('category')}")
    except Exception:
        log.exception("reflection context could not be built; asking generically")

    return ("\n".join(profile_lines), "\n".join(activity_lines[:40]))


def _generate_question(access_token, monday, caller=None):
    """The coach's question for this week, or a fallback if the coach is
    unavailable. Never fails -- the card always has something to show."""
    fallback = _fallback_question(monday)

    if not kakeibo_ai.is_configured():
        return fallback

    profile, activity = _recent_context(access_token, caller=caller)

    ok, payload = kakeibo_ai.weekly_questions(profile, recent_activity=activity or None)
    if not ok:
        # payload is the friendly one-liner; the real exception is already in
        # the log from kakeibo_ai.
        log.warning("weekly question generation failed: %s", payload)
        return fallback

    questions = [q for q in (payload.get("questions") or []) if isinstance(q, str) and q.strip()]
    if not questions:
        return fallback

    # weekly_questions writes 2-3 of them; the card has room for one.
    return questions[0].strip()


def _fetch_week(db, uuid, monday):
    """This week's row, or None if there is not one yet.

    Returns (True, row), (True, None) or (False, error_message).
    """
    try:
        response = (db.table("weekly_reflections")
                      .select(FIELDS)
                      .eq("user_id", uuid)
                      .eq("week_start", monday.isoformat())
                      .limit(1)
                      .execute())

        return (True, response.data[0] if response.data else None)
    except Exception:
        # The raw Postgres error names tables and policies, so it stays in the
        # log -- same policy as kakeibo_ai's friendly errors.
        log.exception("could not read this week's reflection")
        return (False, "Could not load this week's reflection.")


def get_current(access_token):
    """This week's reflection, generating the question on first request.

    Returns (True, {"id", "week_start", "question", "answer", "answered_at"}) or
    (False, error_message).
    """
    caller = user_file.caller_client(access_token)
    if caller[0] is None:
        return (False, caller[1])

    return _get_current(access_token, caller)


def _get_current(access_token, caller):
    """get_current, given a caller that has already been resolved -- so a request
    that needs both this and the tables underneath it checks the token once."""
    uuid, db = caller
    monday = week_start()

    ok, row = _fetch_week(db, uuid, monday)
    if not ok:
        return (False, row)
    if row:
        return (True, row)

    # Nothing for this week yet. Claim the week FIRST, with the free fallback
    # question, and only then pay for a better one: the unique
    # (user_id, week_start) constraint is what makes "once a week per user" true,
    # so nothing may cost money until that row exists. Generating first would
    # mean a failing insert -- or two tabs racing -- billed us every time.
    fallback = _fallback_question(monday)

    try:
        response = (db.table("weekly_reflections")
                      .insert({
                          "user_id": uuid,
                          "week_start": monday.isoformat(),
                          "question": fallback,
                      })
                      .execute())
        row = response.data[0] if response.data else None
    except Exception:
        # Two tabs asking at the same time: whichever insert lost the race hit
        # the unique constraint. That is not an error the user can act on, so it
        # is logged and handled by reading the winner's row back below.
        log.exception("could not start this week's reflection")
        row = None

    if row is None:
        ok, row = _fetch_week(db, uuid, monday)
        if not ok:
            return (False, row)
        if row:
            # Somebody else claimed the week; theirs is the question, and it is
            # theirs to pay for.
            return (True, row)
        return (False, "Could not start this week's reflection.")

    # The week is ours, so this is the one request of the week that can cost a
    # model call. If it fails, the fallback question above is already stored and
    # the card works -- it just is not personalized.
    question = _generate_question(access_token, monday, caller=caller)

    if question and question != fallback:
        try:
            response = (db.table("weekly_reflections")
                          .update({"question": question})
                          .eq("id", row["id"])
                          .execute())
            if response.data:
                row = response.data[0]
        except Exception:
            log.exception("could not store this week's generated question")

    return (True, row)


def save_answer(access_token, answer):
    """Store (or replace) the user's answer to this week's question.

    Returns (True, updated_row) or (False, error_message).
    """
    answer = " ".join((answer or "").split())
    if not answer:
        return (False, "Your reflection is empty.")
    if len(answer) > MAX_ANSWER_CHARS:
        return (False, f"Please keep your reflection under {MAX_ANSWER_CHARS} characters.")

    caller = user_file.caller_client(access_token)
    if caller[0] is None:
        return (False, caller[1])
    db = caller[1]

    # Answering implies the question exists; _get_current creates it if this is
    # the user's first visit of the week. Handing our own caller down means the
    # whole request checks the token once instead of once per read.
    ok, current = _get_current(access_token, caller)
    if not ok:
        return (False, current)

    try:
        response = (db.table("weekly_reflections")
                      .update({
                          "answer": answer,
                          "answered_at": datetime.now(timezone.utc).isoformat(),
                      })
                      .eq("id", current["id"])
                      .execute())

        if not response.data:
            return (False, "Could not save your reflection.")

        return (True, response.data[0])
    except Exception:
        log.exception("could not save reflection %s", current.get("id"))
        return (False, "Could not save your reflection.")


def list_history(access_token, limit=HISTORY_LIMIT):
    """Past weeks that were actually answered, newest first.

    Returns (True, [row, ...]) or (False, error_message).
    """
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    try:
        response = (db.table("weekly_reflections")
                      .select(FIELDS)
                      .eq("user_id", uuid)
                      .not_.is_("answer", "null")
                      .order("week_start", desc=True)
                      .limit(limit)
                      .execute())

        return (True, response.data or [])
    except Exception:
        log.exception("could not read reflection history")
        return (False, "Could not load your past reflections.")
