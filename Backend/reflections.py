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
from datetime import date, datetime, timedelta, timezone

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


def _recent_context(access_token):
    """Build the two short strings the coach needs to personalize a question:
    what the user's budget looks like, and what they spent in the last 7 days.

    Best effort by design -- if either read fails we return what we have. A
    generic question is a much better outcome than no card at all.
    """
    profile_lines = []
    activity_lines = []

    # What the user told us in the onboarding interview, if they did it. This is
    # the part that makes the question about their goals rather than about the
    # numbers alone -- everything below is derived from spending, which says what
    # they did but nothing about what they were trying to do.
    ok, profile_md = reports.get_profile(access_token)
    if ok and profile_md:
        profile_lines.append(profile_md.strip())

    ok, expenses_data = expenses.get_expenses(access_token)
    if not ok:
        log.info("reflection context: could not read expenses: %s", expenses_data)
        expenses_data = []

    ok, funds_data = expenses.get_funds(access_token)
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

    # Only the last 7 days count as "this week's activity". purchase_date comes
    # back from Postgres as a "YYYY-MM-DD" string, so a string compare is an
    # ordering compare -- but anything unexpected is skipped rather than crashing
    # the card.
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    for expense in expenses_data:
        purchase_date = expense.get("purchase_date")
        if not isinstance(purchase_date, str) or purchase_date < cutoff:
            continue
        activity_lines.append(
            f"- {purchase_date}: ${expense.get('amount')} on {expense.get('category')}")

    return ("\n".join(profile_lines), "\n".join(activity_lines[:40]))


def _generate_question(access_token, monday):
    """The coach's question for this week, or a fallback if the coach is
    unavailable. Never fails -- the card always has something to show."""
    fallback = FALLBACK_QUESTIONS[monday.isocalendar()[1] % len(FALLBACK_QUESTIONS)]

    if not kakeibo_ai.is_configured():
        return fallback

    profile, activity = _recent_context(access_token)

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


def get_current(access_token):
    """This week's reflection, generating the question on first request.

    Returns (True, {"id", "week_start", "question", "answer", "answered_at"}) or
    (False, error_message).
    """
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    monday = week_start()

    try:
        response = (db.table("weekly_reflections")
                      .select("id, week_start, question, answer, answered_at")
                      .eq("user_id", uuid)
                      .eq("week_start", monday.isoformat())
                      .limit(1)
                      .execute())

        if response.data:
            return (True, response.data[0])
    except Exception as e:
        return (False, f"Could not load this week's reflection: {e}")

    # Nothing for this week yet, so this is the one request of the week that
    # costs a model call.
    question = _generate_question(access_token, monday)

    try:
        response = (db.table("weekly_reflections")
                      .insert({
                          "user_id": uuid,
                          "week_start": monday.isoformat(),
                          "question": question,
                      })
                      .execute())

        if not response.data:
            return (False, "Could not start this week's reflection.")

        return (True, response.data[0])
    except Exception as e:
        # Two tabs asking at the same time: whichever insert lost the race hit
        # the unique (user_id, week_start) constraint. Read the winner's row back
        # rather than reporting an error the user cannot act on.
        try:
            response = (db.table("weekly_reflections")
                          .select("id, week_start, question, answer, answered_at")
                          .eq("user_id", uuid)
                          .eq("week_start", monday.isoformat())
                          .limit(1)
                          .execute())
            if response.data:
                return (True, response.data[0])
        except Exception:
            pass

        return (False, f"Could not start this week's reflection: {e}")


def save_answer(access_token, answer):
    """Store (or replace) the user's answer to this week's question.

    Returns (True, updated_row) or (False, error_message).
    """
    answer = " ".join((answer or "").split())
    if not answer:
        return (False, "Your reflection is empty.")
    if len(answer) > MAX_ANSWER_CHARS:
        return (False, f"Please keep your reflection under {MAX_ANSWER_CHARS} characters.")

    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    # Answering implies the question exists; get_current creates it if this is
    # the user's first visit of the week.
    ok, current = get_current(access_token)
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
    except Exception as e:
        return (False, f"Could not save your reflection: {e}")


def list_history(access_token, limit=HISTORY_LIMIT):
    """Past weeks that were actually answered, newest first.

    Returns (True, [row, ...]) or (False, error_message).
    """
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    try:
        response = (db.table("weekly_reflections")
                      .select("id, week_start, question, answer, answered_at")
                      .eq("user_id", uuid)
                      .not_.is_("answer", "null")
                      .order("week_start", desc=True)
                      .limit(limit)
                      .execute())

        return (True, response.data or [])
    except Exception as e:
        return (False, f"Could not load your past reflections: {e}")
