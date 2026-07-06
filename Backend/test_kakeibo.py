"""
Standalone test harness for the Kakeibo AI framework.

Runs every function in kakeibo_ai.py against the live API with sample data.
NO Flask and NO Supabase required — this is how the team can try out and tune
the AI coach before the rest of the app exists.

Setup:
    pip install -r requirements.txt
    copy sampleENV to .env and put a real OPENAI_API_KEY in it
Run from the Backend/ folder:
    python test_kakeibo.py

Optionally try a different model without editing code:
    KAKEIBO_MODEL=gpt-4o-mini python test_kakeibo.py     (mac/Linux)
    $env:KAKEIBO_MODEL="gpt-4o-mini"; python test_kakeibo.py   (PowerShell)
"""

import json

import kakeibo_ai


def show(title, ok, payload):
    print("\n" + "=" * 70)
    print(title, "  ->  ", "OK" if ok else "FAILED")
    print("=" * 70)
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2))
    else:
        print(payload)


# Sample data shared across the tests --------------------------------------
SAMPLE_PROFILE = {
    "goals": ["save $1000 for an emergency fund", "stop impulse buying"],
    "priorities": ["paying rent on time", "occasional treats with friends"],
    "money_personality": "spends emotionally when stressed but wants to learn",
    "focus_areas": ["impulse spending", "building savings"],
}

SAMPLE_TRANSACTIONS = [
    {"date": "2026-06-02", "item": "Rent", "amount": 800, "category": "housing", "tag": "need"},
    {"date": "2026-06-03", "item": "Groceries", "amount": 95, "category": "food", "tag": "need"},
    {"date": "2026-06-05", "item": "Coffee shop", "amount": 6.50, "category": "food", "tag": "want"},
    {"date": "2026-06-07", "item": "Online game skin", "amount": 25, "category": "entertainment", "tag": "want"},
    {"date": "2026-06-10", "item": "Bus pass", "amount": 40, "category": "transport", "tag": "need"},
    {"date": "2026-06-14", "item": "Concert ticket", "amount": 75, "category": "culture", "tag": "want"},
    {"date": "2026-06-18", "item": "Phone screen repair", "amount": 110, "category": "unexpected", "tag": "emergency"},
    {"date": "2026-06-22", "item": "Coffee shop", "amount": 6.50, "category": "food", "tag": "want"},
]


def main():
    print(f"Using model: {kakeibo_ai.DEFAULT_MODEL}")

    # 1. Purchase reflection
    ok, payload = kakeibo_ai.reflect_on_purchase(
        item="Wireless earbuds",
        amount=180,
        category="electronics",
        user_note="My current ones still work but these look cool.",
    )
    show("1. reflect_on_purchase", ok, payload)

    # 2. Monthly analysis
    ok, payload = kakeibo_ai.monthly_analysis(
        SAMPLE_TRANSACTIONS, income=1600, savings_goal=200
    )
    show("2. monthly_analysis", ok, payload)

    # 3. Weekly questions
    ok, payload = kakeibo_ai.weekly_questions(
        SAMPLE_PROFILE,
        recent_activity="Bought coffee out 4 times and one concert ticket this week.",
    )
    show("3. weekly_questions", ok, payload)

    # 4. Coaching chat
    history = [
        {"role": "user", "content": "I keep overspending on takeout. How do I stop?"},
    ]
    ok, payload = kakeibo_ai.ask_coach(history, user_context=str(SAMPLE_PROFILE))
    show("4. ask_coach", ok, payload)

    # 5. Profile summary from an onboarding interview
    transcript = (
        "Coach: What do you want to get better at with money?\n"
        "User: I never save anything and I want an emergency fund.\n"
        "Coach: What tends to trip you up?\n"
        "User: I buy stuff online late at night when I'm bored or stressed.\n"
        "Coach: What matters most to you right now?\n"
        "User: Making rent and still being able to hang out with friends sometimes."
    )
    ok, payload = kakeibo_ai.summarize_profile(transcript)
    show("5. summarize_profile", ok, payload)


if __name__ == "__main__":
    main()
