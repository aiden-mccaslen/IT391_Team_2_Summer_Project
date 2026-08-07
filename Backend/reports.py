"""
The two generated Kakeibo documents: the monthly review and the user's profile.

Both are produced by kakeibo_ai, rendered to Markdown here, and stored as files in
the private "kakeibo-docs" Supabase Storage bucket (see
migrations/004_documents_storage.sql) rather than in a table. They are read whole
and never queried by their contents, so the file IS the record -- and "have we
already generated this month?" becomes a file lookup.

That lookup is what keeps the cost down: monthly_analysis is the most expensive
call in the app, and without the stored copy every dashboard load would pay for it
again. Regenerating is always possible, but it has to be asked for.

Like expenses.py and reflections.py, every function takes the caller's access token
and builds its own per-user client through user.caller_client(), so Row Level
Security does the ownership check inside Supabase. Every function returns a
(success, payload) tuple, same as the rest of the backend.
"""

import logging
import re
from datetime import datetime, timezone

from storage3.exceptions import StorageApiError

import budget
import expenses
import kakeibo_ai
import user as user_file


log = logging.getLogger("kakeibo.reports")

BUCKET = "kakeibo-docs"

# The interview is a handful of short answers, not an essay.
MAX_TRANSCRIPT_CHARS = 8000

# A month key goes into a storage object path, so it is checked against this
# before it is used rather than trusted because it came from a query string.
MONTH_KEY_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# What the user sees when storage is unreachable. The real error goes to the log
# -- same policy as kakeibo_ai's friendly errors.
STORAGE_UNAVAILABLE = "Your documents could not be reached right now. Please try again in a moment."


def month_key(when=None):
    """The "YYYY-MM" that identifies a monthly report. Defaults to this month."""
    when = when or datetime.now(timezone.utc)
    return when.strftime("%Y-%m")


def is_month_key(key):
    """Whether `key` is a "YYYY-MM" we are willing to build a path out of.

    `?month=` reaches _monthly_path() and becomes part of an object name, so
    anything that is not exactly a year and a month is refused here. Storage's
    own access rules are the backstop, not the check.
    """
    return isinstance(key, str) and bool(MONTH_KEY_PATTERN.match(key))


def _month_title(key):
    """"2026-08" -> "August 2026", for the heading."""
    try:
        return datetime.strptime(key, "%Y-%m").strftime("%B %Y")
    except ValueError:
        return key


def _profile_path(uuid):
    return f"{uuid}/profile.md"


def _monthly_path(uuid, key):
    return f"{uuid}/monthly/{key}.md"


# ---------------------------------------------------------------------------
# Storage helpers.
# ---------------------------------------------------------------------------
def _is_missing_object(exc):
    """Whether a storage exception means "that file is not there" as opposed to
    "the read failed".

    The distinction is the whole point of _read_md: a missing object is the
    signal to generate, and generating is the expensive path. A denied policy or
    a 5xx must NOT look like a missing object, or every page load pays for a
    fresh model run while the write that would have cached it keeps failing too.
    """
    if not isinstance(exc, StorageApiError):
        return False

    try:
        status = int(exc.status)
    except (TypeError, ValueError):
        status = None

    if status == 404:
        return True

    # Older storage-api versions answer a missing object with a 400 whose body
    # says so, so the status alone is not enough to tell them apart.
    if status == 400:
        text = f"{exc.code} {exc.message}".lower()
        return "not found" in text or "not_found" in text

    return False


def _read_md(db, path):
    """A stored Markdown document.

    Returns (True, text), (True, None) when the document has not been generated
    yet, or (False, message) when the read itself failed. "Not there" and "could
    not look" are different answers and callers must not treat them alike.
    """
    try:
        return (True, db.storage.from_(BUCKET).download(path).decode("utf-8"))
    except Exception as e:
        if _is_missing_object(e):
            log.debug("no stored document at %s", path)
            return (True, None)

        log.exception("could not read document at %s", path)
        return (False, STORAGE_UNAVAILABLE)


def _write_md(db, path, text):
    """Write (or replace) a Markdown document. Returns (True, None) or (False, msg)."""
    try:
        db.storage.from_(BUCKET).upload(
            path,
            text.encode("utf-8"),
            # upsert so regenerating overwrites instead of colliding with itself.
            file_options={"content-type": "text/markdown", "upsert": "true"},
        )
        return (True, None)
    except Exception:
        # The exception text can carry bucket names and policy details, so it
        # stays in the log and the caller gets the generic line.
        log.exception("could not store document at %s", path)
        return (False, STORAGE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Turning our tables into the shape kakeibo_ai expects.
# ---------------------------------------------------------------------------
def _transactions_for(access_token, key):
    """This month's expenses as the transaction dicts monthly_analysis documents.

    Returns (transactions, income). Best effort -- a read failure yields an empty
    list, and the caller turns that into "nothing logged yet" rather than an error.

    NOTE: the expenses table has no item/description column, so `item` is the
    category. The review is therefore category-level; it will get sharper for free
    if an item column is ever added.
    """
    ok, expenses_data = expenses.get_expenses(access_token)
    if not ok:
        log.info("monthly report: could not read expenses: %s", expenses_data)
        expenses_data = []

    ok, funds_data = expenses.get_funds(access_token)
    if not ok:
        log.info("monthly report: could not read funds: %s", funds_data)
        funds_data = []

    income = None
    if funds_data:
        try:
            income = float(funds_data[0]["amount"])
        except (TypeError, ValueError, KeyError):
            income = None

    transactions = []
    for row in expenses_data:
        purchase_date = row.get("purchase_date")
        # purchase_date is a "YYYY-MM-DD" string from Postgres, so the month is a
        # prefix compare. Anything unexpected is skipped rather than crashing.
        if not isinstance(purchase_date, str) or not purchase_date.startswith(key):
            continue

        category = row.get("category") or "uncategorized"
        transactions.append({
            "date": purchase_date,
            "item": category,
            "amount": row.get("amount"),
            "category": category,
            # The 50/30/20 bucket, so the model can see our split alongside its
            # own four Kakeibo buckets.
            "tag": (budget.CATEGORY_MAP.get(category) or "uncategorized").lower(),
        })

    return (transactions, income)


# ---------------------------------------------------------------------------
# Rendering. Pure functions -- no I/O, no model calls.
# ---------------------------------------------------------------------------
def _bullets(items):
    lines = [f"- {item}" for item in (items or []) if str(item).strip()]
    return "\n".join(lines) if lines else "- (nothing noted)"


def _render_monthly_md(data, key):
    """The structured monthly_analysis payload as a Markdown document."""
    categories = data.get("categories") or {}

    return "\n".join([
        f"# Monthly review — {_month_title(key)}",
        "",
        (data.get("summary") or "").strip(),
        "",
        "## Where the money went",
        "",
        f"**Survival** — {categories.get('survival', '')}".rstrip(),
        "",
        f"**Optional** — {categories.get('optional', '')}".rstrip(),
        "",
        f"**Culture** — {categories.get('culture', '')}".rstrip(),
        "",
        f"**Unexpected** — {categories.get('unexpected', '')}".rstrip(),
        "",
        "## Wins",
        "",
        _bullets(data.get("wins")),
        "",
        "## Leaks",
        "",
        _bullets(data.get("leaks")),
        "",
        "## Questions for next month",
        "",
        _bullets(data.get("questions_next_month")),
        "",
        "---",
        "",
        (data.get("encouragement") or "").strip(),
        "",
    ])


def _render_profile_md(data):
    """The structured summarize_profile payload as a Markdown document."""
    return "\n".join([
        "# Your money profile",
        "",
        (data.get("money_personality") or "").strip(),
        "",
        "## Goals",
        "",
        _bullets(data.get("goals")),
        "",
        "## Priorities",
        "",
        _bullets(data.get("priorities")),
        "",
        "## Where we will help most",
        "",
        _bullets(data.get("focus_areas")),
        "",
    ])


# ---------------------------------------------------------------------------
# The monthly review.
# ---------------------------------------------------------------------------
def get_monthly(access_token, key=None, refresh=False):
    """This month's Kakeibo review, generating it only if it is not already stored.

    Returns (True, {"month", "title", "markdown", "generated"}) or
    (False, error_message). `generated` says whether this call paid for a model
    run, which is what the UI uses to explain a slow first load.
    """
    key = key or month_key()
    if not is_month_key(key):
        # Deliberately does not echo what was sent -- it goes straight back to
        # the page, and there is nothing useful in repeating it.
        return (False, "That is not a month I can write a review for.")

    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    path = _monthly_path(uuid, key)

    if not refresh:
        ok, stored = _read_md(db, path)
        if not ok:
            # A failed read is NOT "not written yet". Generating here would mean
            # paying for a model run on every page load for as long as storage
            # stays broken, since the write that caches it would fail too.
            return (False, stored)

        if stored is not None:
            return (True, {
                "month": key,
                "title": _month_title(key),
                "markdown": stored,
                "generated": False,
            })

    if not kakeibo_ai.is_configured():
        return (False, "The coach is not available right now, so a review cannot "
                       "be written. Please try again later.")

    transactions, income = _transactions_for(access_token, key)
    if not transactions:
        return (False, f"There are no expenses logged for {_month_title(key)} yet, "
                       f"so there is nothing to review.")

    # savings_goal stays None until the savings feature exists to set one.
    ok, payload = kakeibo_ai.monthly_analysis(transactions, income=income)
    if not ok:
        # payload is the friendly one-liner; kakeibo_ai already logged the real
        # exception.
        return (False, payload)

    markdown = _render_monthly_md(payload, key)

    ok, error = _write_md(db, path, markdown)
    if not ok:
        # The review exists and was paid for -- hand it over even though we could
        # not keep a copy. Losing the cache is worse than losing the report.
        log.warning("monthly report for %s not stored: %s", key, error)

    return (True, {
        "month": key,
        "title": _month_title(key),
        "markdown": markdown,
        "generated": True,
    })


# ---------------------------------------------------------------------------
# The profile, from the onboarding interview.
# ---------------------------------------------------------------------------
def get_profile(access_token, caller=None):
    """The stored profile, or (True, None) if the user has not done the interview.

    "Not done yet" is a success with nothing in it, not an error -- the caller
    shows the interview instead. A read that actually failed is (False, message).

    `caller` is an already-resolved (uuid, client) pair, as in expenses.py.
    """
    uuid, db = caller or user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    return _read_md(db, _profile_path(uuid))


def save_profile(access_token, transcript):
    """Summarize an onboarding interview into a profile and store it.

    `transcript` is the interview as a string, or a list of Q&A turns.
    Returns (True, {"markdown", "stored"}) or (False, error_message). `stored`
    is False when the profile was written but could not be saved, so the caller
    can say so rather than claiming it kept it.
    """
    if isinstance(transcript, list):
        transcript = "\n".join(str(turn) for turn in transcript)
    transcript = (transcript or "").strip()

    if not transcript:
        return (False, "The interview was empty.")
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        return (False, "That interview is too long to summarize.")

    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    if not kakeibo_ai.is_configured():
        return (False, "The coach is not available right now, so your profile "
                       "cannot be written. Please try again later.")

    ok, payload = kakeibo_ai.summarize_profile(transcript)
    if not ok:
        return (False, payload)

    markdown = _render_profile_md(payload)

    ok, error = _write_md(db, _profile_path(uuid), markdown)
    if not ok:
        # The profile exists and was paid for. Hand it over even though we could
        # not keep a copy -- same call as get_monthly makes. Throwing it away
        # would mean the user re-runs the whole interview for nothing.
        log.warning("profile not stored: %s", error)

    return (True, {"markdown": markdown, "stored": ok})
