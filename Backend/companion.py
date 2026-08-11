"""
The dashboard's companion widget -- a small Tamagotchi-style mascot whose mood
and level are a cosmetic readout of the user's real budgeting behavior. It
never gates anything: it only reflects state that other features already own.

That is the load-bearing design rule of this file, so it is worth stating
plainly: companion.py READS expenses.py, budget.py and reflections.py, but
nothing in those files imports or calls into this one. The dependency arrow
points one way, out from here. That is what makes the feature removable --
delete this file, its migrations (migrations/005_companion.sql,
migrations/006_companion_stats.sql), and the two frontend companion files,
and every other module keeps working unmodified.

The one deliberate exception: app.py's POST /chat calls
record_chat_interaction() after a successful reply, best-effort, guarded the
same way every other companion route is (`companion is not None and
COMPANION_ENABLED`). A failure in there is logged and swallowed -- it must
never turn a working chat reply into a failed request just because the
cosmetic widget could not be updated. That is the only place outside this
file that reaches in; chat_history, budget, expenses and reflections still
have no idea this module exists.

Like reflections.py, every function here takes the caller's access token and
builds its own per-user client through user.caller_client(), so Row Level
Security does the ownership check inside the database rather than in the
Flask layer. Every function returns a (success, payload) tuple, same as the
rest of the backend.

Mood/level are computed FRESH on every call from real signals -- an activity
streak built from expense timestamps, budget warnings from
budget.evaluate_budget(), and a reflection streak from weekly_reflections --
rather than being pushed in by hooks in those other files. The stored row
persists the most recent computed value (so a page that only shows the
cached row still sees something sensible), but this file is the only writer
of it.

Happiness/hunger work the same way but on a shorter, game-ier loop: they
decay over real elapsed time (see _synced_stats) and get boosted by
record_chat_interaction(). Chatting with the coach is the "feed/play with
your companion" action -- there is no separate button for it, on purpose:
using the app IS the interaction.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import budget
import expenses
import reflections
import user as user_file


log = logging.getLogger("kakeibo.companion")

# A user-chosen name; kept short for the same reason the reflection answer is
# capped -- this is a dashboard widget, not a form.
NAME_MAX_CHARS = 40

# The moods the pure scoring function below can hand back. Kept as constants
# rather than bare strings so a typo in one place fails loudly instead of
# silently falling through to the neutral dialogue pool.
MOOD_POSITIVE = "positive"
MOOD_NEUTRAL = "neutral"
MOOD_NEGLECTED = "neglected"

# Growth caps. Kept small on purpose -- this is flavor, not a progression
# system with content behind it, so there is nothing to gain by letting the
# numbers run higher than a glance can register.
MAX_LEVEL = 10
STAGE_COUNT = 4  # 0..3

# Happiness/hunger: both 0..100, decaying toward 0 over real elapsed time and
# boosted by chatting with the coach (record_chat_interaction). Hunger decays
# faster than happiness -- the same "needs more frequent attention" split a
# real Tamagotchi has between the two.
STAT_MIN = 0
STAT_MAX = 100
DEFAULT_HAPPINESS = 70
DEFAULT_HUNGER = 70
HAPPINESS_DECAY_PER_HOUR = 0.4
HUNGER_DECAY_PER_HOUR = 1.0

# One chat exchange's worth of "feeding"/"playing". Deliberately generous
# relative to the decay rates above -- a single conversation should visibly
# help, not round to nothing.
CHAT_HAPPINESS_BOOST = 15
CHAT_HUNGER_BOOST = 20

# The plain feed button: mostly about hunger, a little happiness, and -- unlike
# the chat boost -- free (no model call, so no reserve_send guard needed).
# Smaller than the chat boost on purpose, so chatting stays the better payoff
# and the button is a top-up, not a strictly-better substitute. No cooldown:
# both stats cap at STAT_MAX, so mashing the button just gets you to full
# faster and then does nothing -- that ceiling is the only throttle it needs.
FEED_HUNGER_BOOST = 15
FEED_HAPPINESS_BOOST = 5

# At or below this, either stat alone reads as neglected regardless of the
# budgeting streak -- the whole point of wiring chat in is that ignoring the
# companion itself now has a visible consequence, not just ignoring the budget.
LOW_STAT_THRESHOLD = 25

FIELDS = ("user_id, name, level, stage, streak, happiness, hunger, "
          "created_at, last_interacted_at, stats_synced_at")

# Used the same way FALLBACK_QUESTIONS is used in reflections.py: a small
# static pool, keyed on the day so the line still changes day to day, with no
# hard dependency on the AI layer being configured (the companion never calls
# it at all -- these are the only lines it ever shows).
DIALOGUE_LINES = {
    MOOD_POSITIVE: [
        "You're on a roll! I love spending this streak with you.",
        "Look at that streak -- I'm so proud of you right now.",
        "We're doing great this week. I'm having a lot of fun with you!",
        "Your 50/30/20 split looks healthy right now. You're amazing.",
    ],
    MOOD_NEUTRAL: [
        "I'm doing okay -- come say hi and I'll perk right up.",
        "Steady as she goes. I'd love to hear how your week's going.",
        "Nothing's wrong, I just missed you a little. Tell me something!",
        "Things are quiet. Pop in and chat with me for a bit?",
    ],
    MOOD_NEGLECTED: [
        "I've missed you -- it's been a while since we talked.",
        "It's been quiet without you. Come say hi so I know you're okay!",
        "I'm feeling a little lonely. Even a quick hello would make my day.",
        "Things have been a bit rough lately -- I'm here whenever you're ready.",
    ],
}


def compute_activity_streak(purchase_dates, today=None):
    """Pure: the number of consecutive days, ending today (or yesterday, so a
    day that has not been logged YET does not zero the streak), that have at
    least one expense logged.

    `purchase_dates` is an iterable of already-fetched date values -- either
    "YYYY-MM-DD" strings (what Postgres hands back for a date column) or
    `datetime.date` objects. This function does no I/O, so it can be unit
    tested without Supabase, the same way budget.calculate_totals is kept
    separate from the network calls around it.
    """
    days = set()
    for value in purchase_dates or []:
        parsed = value
        if isinstance(parsed, str):
            try:
                parsed = date.fromisoformat(parsed[:10])
            except ValueError:
                continue
        if isinstance(parsed, datetime):
            parsed = parsed.date()
        if isinstance(parsed, date):
            days.add(parsed)

    if not days:
        return 0

    today = today or datetime.now(timezone.utc).date()
    cursor = today if today in days else today - timedelta(days=1)

    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def score_companion(streak_days, warning_count, reflection_weeks):
    """Pure: turns the three real signals into a mood/level/stage. No I/O --
    this is the one function a unit test needs to exercise the whole scale,
    mirroring how budget.calculate_budget is kept separate from the Supabase
    calls around it.

    Returns {"mood", "level", "stage"}.
    """
    streak_days = max(0, int(streak_days or 0))
    warning_count = max(0, int(warning_count or 0))
    reflection_weeks = max(0, int(reflection_weeks or 0))

    if streak_days == 0 or warning_count >= 2:
        mood = MOOD_NEGLECTED
    elif warning_count == 0 and streak_days >= 3:
        mood = MOOD_POSITIVE
    else:
        mood = MOOD_NEUTRAL

    # Activity counts for more than reflections, since it happens far more
    # often; both are capped so the number cannot climb forever on a long
    # streak alone.
    xp = min(streak_days, 14) + min(reflection_weeks, 8) * 2
    level = min(MAX_LEVEL, xp // 3)
    stage = min(STAGE_COUNT - 1, level // ((MAX_LEVEL // STAGE_COUNT) + 1))

    return {"mood": mood, "level": level, "stage": stage}


def _decay(value, per_hour, hours_elapsed):
    """Pure: linear decay toward STAT_MIN, clamped to the stat's range. The
    other half of score_companion's "pure scoring, no I/O" split -- this is
    what a unit test exercises for the decay curve itself."""
    hours_elapsed = max(0.0, hours_elapsed or 0.0)
    return max(STAT_MIN, min(STAT_MAX, int(round((value or 0) - per_hour * hours_elapsed))))


def _hours_since(timestamp_iso):
    """Pure-ish (reads the clock, nothing else): hours between `timestamp_iso`
    and now, or 0 if it is missing or unparseable -- a brand-new row, or one
    from before this column existed, should not be treated as having decayed
    for however long the row happens to be old."""
    if not timestamp_iso:
        return 0.0
    try:
        then = datetime.fromisoformat(str(timestamp_iso).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 3600)


def _synced_stats(row):
    """Happiness/hunger with whatever decay is owed since this row's last
    sync applied, WITHOUT persisting it -- every caller is about to write
    something anyway (get_state refreshes level/stage/streak regardless;
    record_chat_interaction is about to add the chat boost on top), so there
    is always exactly one write per read and never a dangling unsaved decay.

    Falls back to created_at when stats_synced_at is still null -- true for
    every row that existed before this column did, and for a row that was
    just created this call (_ensure_row does not stamp it).
    """
    hours = _hours_since(row.get("stats_synced_at") or row.get("created_at"))
    happiness = _decay(row.get("happiness", DEFAULT_HAPPINESS), HAPPINESS_DECAY_PER_HOUR, hours)
    hunger = _decay(row.get("hunger", DEFAULT_HUNGER), HUNGER_DECAY_PER_HOUR, hours)
    return happiness, hunger


def _dialogue_line(mood, seed):
    """One line from the pool for this mood, picked by `seed` so the same
    mood does not always show the exact same sentence."""
    lines = DIALOGUE_LINES.get(mood) or DIALOGUE_LINES[MOOD_NEUTRAL]
    return lines[seed % len(lines)]


def _signals(access_token):
    """The three real signals the companion reflects, gathered best-effort --
    same policy as reflections._recent_context: any failure in here degrades
    to "nothing to report" rather than failing the whole widget.

    Returns (streak_days, warning_count, reflection_weeks).
    """
    streak_days = 0
    warning_count = 0

    try:
        ok, expenses_data = expenses.get_expenses(access_token)
        if not ok:
            log.info("companion signals: could not read expenses: %s", expenses_data)
            expenses_data = []

        purchase_dates = [e.get("purchase_date") for e in expenses_data
                           if e.get("purchase_date")]
        streak_days = compute_activity_streak(purchase_dates)

        ok, funds_data = expenses.get_balance(access_token)
        if not ok:
            log.info("companion signals: could not read funds: %s", funds_data)
            funds_data = []

        income = 0.0
        if funds_data:
            try:
                income = float(funds_data[0]["amount"])
            except (TypeError, ValueError, KeyError):
                income = 0.0

        summary = budget.calculate_budget(income, expenses_data)
        warning_count = len(budget.evaluate_budget(summary))
    except Exception:
        log.exception("companion signals: could not read expense/budget data")

    reflection_weeks = _reflection_streak_weeks(access_token)

    return (streak_days, warning_count, reflection_weeks)


def _reflection_streak_weeks(access_token):
    """How many weeks in a row the user has answered their weekly reflection,
    counting backward from this week (or last week, on the same "not logged
    yet does not break the streak" grace as compute_activity_streak).

    Reads reflections.py rather than duplicating its query -- companion.py is
    allowed to read the other modules, just never the other way around.
    """
    try:
        ok, history = reflections.list_history(access_token)
        if not ok or not history:
            return 0

        weeks = set()
        for row in history:
            week_start = row.get("week_start")
            if isinstance(week_start, str):
                try:
                    weeks.add(date.fromisoformat(week_start[:10]))
                except ValueError:
                    continue

        if not weeks:
            return 0

        cursor = reflections.week_start()
        if cursor not in weeks:
            cursor -= timedelta(days=7)

        streak = 0
        while cursor in weeks:
            streak += 1
            cursor -= timedelta(days=7)

        return streak
    except Exception:
        log.exception("companion signals: could not read reflection history")
        return 0


def _fetch_row(db, uuid):
    """The stored row, or None if there is not one yet.

    Returns (True, row_or_None) or (False, error_message).
    """
    try:
        response = (db.table("companion_state")
                      .select(FIELDS)
                      .eq("user_id", uuid)
                      .limit(1)
                      .execute())

        return (True, response.data[0] if response.data else None)
    except Exception:
        log.exception("could not read companion state")
        return (False, "Could not load your companion.")


def _ensure_row(db, uuid):
    """The stored row, creating one with defaults on first call -- same
    race-handled insert pattern as reflections._get_current: claim the row
    first, and if two tabs raced, read back whoever won rather than erroring.
    """
    ok, row = _fetch_row(db, uuid)
    if not ok:
        return (False, row)
    if row:
        return (True, row)

    try:
        response = (db.table("companion_state")
                      .insert({"user_id": uuid})
                      .execute())
        row = response.data[0] if response.data else None
    except Exception:
        # Most likely two tabs racing to create the same row; the unique
        # primary key means only one insert wins, and that is not an error
        # the user can act on.
        log.exception("could not create companion state")
        row = None

    if row is None:
        ok, row = _fetch_row(db, uuid)
        if not ok:
            return (False, row)
        if row:
            return (True, row)
        return (False, "Could not set up your companion.")

    return (True, row)


def get_state(access_token):
    """The companion's current mood, level and dialogue line, computed fresh
    from real signals every time this is called.

    Returns (True, {"name", "mood", "level", "stage", "streak", "happiness",
    "hunger", "dialogue", "last_interacted_at"}) or (False, error_message).
    """
    caller = user_file.caller_client(access_token)
    if caller[0] is None:
        return (False, caller[1])
    uuid, db = caller

    ok, row = _ensure_row(db, uuid)
    if not ok:
        return (False, row)

    streak_days, warning_count, reflection_weeks = _signals(access_token)
    scored = score_companion(streak_days, warning_count, reflection_weeks)

    happiness, hunger = _synced_stats(row)
    # A neglected companion is neglected whether that shows up as a broken
    # budgeting streak or as nobody having chatted with it -- either stat
    # alone is enough to override an otherwise fine budgeting-based mood.
    if happiness <= LOW_STAT_THRESHOLD or hunger <= LOW_STAT_THRESHOLD:
        scored["mood"] = MOOD_NEGLECTED

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        response = (db.table("companion_state")
                      .update({
                          "level": scored["level"],
                          "stage": scored["stage"],
                          "streak": streak_days,
                          "happiness": happiness,
                          "hunger": hunger,
                          "stats_synced_at": now_iso,
                          "last_interacted_at": now_iso,
                      })
                      .eq("user_id", uuid)
                      .execute())
        if response.data:
            row = response.data[0]
    except Exception:
        # Not fatal -- everything returned below is computed fresh regardless
        # of whether the persisted row could be updated.
        log.exception("could not update companion state")

    today_ordinal = datetime.now(timezone.utc).timetuple().tm_yday

    return (True, {
        "name": row.get("name"),
        "mood": scored["mood"],
        "level": scored["level"],
        "stage": scored["stage"],
        "streak": streak_days,
        "happiness": happiness,
        "hunger": hunger,
        "dialogue": _dialogue_line(scored["mood"], today_ordinal),
        "last_interacted_at": row.get("last_interacted_at"),
    })


def _boost(access_token, happiness_boost, hunger_boost):
    """Shared by record_chat_interaction and feed: apply whatever decay is
    owed, then add a boost, capped at STAT_MAX.

    Returns (True, {"happiness", "hunger"}) or (False, error_message).
    """
    caller = user_file.caller_client(access_token)
    if caller[0] is None:
        return (False, caller[1])
    uuid, db = caller

    ok, row = _ensure_row(db, uuid)
    if not ok:
        return (False, row)

    happiness, hunger = _synced_stats(row)
    happiness = min(STAT_MAX, happiness + happiness_boost)
    hunger = min(STAT_MAX, hunger + hunger_boost)

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db.table("companion_state").update({
            "happiness": happiness,
            "hunger": hunger,
            "stats_synced_at": now_iso,
            "last_interacted_at": now_iso,
        }).eq("user_id", uuid).execute()
    except Exception:
        log.exception("could not update companion stats for %s", uuid)
        return (False, "Could not update your companion.")

    return (True, {"happiness": happiness, "hunger": hunger})


def record_chat_interaction(access_token):
    """Called from POST /chat after a successful reply: chatting with the
    coach is one way to feed/play with your companion (see feed() for the
    low-friction alternative), so this is the only thing outside this file
    that ever writes here (see the module docstring).

    Best-effort by design -- the caller in app.py must never let a failure
    here turn a working chat reply into a failed request.

    Returns (True, {"happiness", "hunger"}) or (False, error_message).
    """
    return _boost(access_token, CHAT_HAPPINESS_BOOST, CHAT_HUNGER_BOOST)


def feed(access_token):
    """The plain feed button: a free, instant top-up with no model call and
    no rate-limit guard needed -- for someone who just wants to check in on
    their companion without composing a chat message.

    Returns (True, {"happiness", "hunger"}) or (False, error_message).
    """
    return _boost(access_token, FEED_HAPPINESS_BOOST, FEED_HUNGER_BOOST)


def set_name(access_token, name):
    """Store (or replace) the user's chosen name for their companion.

    Returns (True, row) or (False, error_message).
    """
    name = " ".join((name or "").split())
    if not name:
        return (False, "Give your companion a name.")
    if len(name) > NAME_MAX_CHARS:
        return (False, f"Keep the name under {NAME_MAX_CHARS} characters.")

    caller = user_file.caller_client(access_token)
    if caller[0] is None:
        return (False, caller[1])
    uuid, db = caller

    ok, row = _ensure_row(db, uuid)
    if not ok:
        return (False, row)

    try:
        response = (db.table("companion_state")
                      .update({
                          "name": name,
                          "last_interacted_at": datetime.now(timezone.utc).isoformat(),
                      })
                      .eq("user_id", uuid)
                      .execute())

        if not response.data:
            return (False, "Could not save your companion's name.")

        return (True, response.data[0])
    except Exception:
        log.exception("could not save companion name for %s", uuid)
        return (False, "Could not save your companion's name.")
