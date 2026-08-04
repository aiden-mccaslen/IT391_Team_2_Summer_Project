from supabase import create_client
from datetime import date, datetime
import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Need to implement fee monitoring

def add_fee(access_token, fee_name, due_date, fee_amount, reminder_days):

    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id

        response = (
            supabase_client.table("fees")
            .insert({
                "user_id": uuid,
                "fee_name": fee_name,
                "due_date": due_date,
                "fee_amount": fee_amount,
                "reminder_days": reminder_days,
                "paid": False
            })
            .execute()
        )

        return (True, response)

    except Exception as e:
        return (False, str(e))

def get_fees(access_token):

    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id

        response = (
            supabase_client.table("fees")
            .select("*")
            .eq("user_id", uuid)
            .execute()
        )

        return (True, response.data)

    except Exception as e:
        return (False, str(e))

def check_fee_warnings(fees): #fees come form the result of get_fees
    """
    Returns a list of warnings for fees that are due soon or overdue.
    """

    warnings = []

    today = date.today()

    for fee in fees:

        # Skip fees that have already been paid
        if fee["paid"]:
            continue

        due_date = datetime.strptime(
            fee["due_date"], "%Y-%m-%d"
        ).date()

        days_remaining = (due_date - today).days

        if days_remaining < 0:
            warnings.append({
                "fee_name": fee["fee_name"],
                "status": "Overdue",
                "message": f"You may have incurred a ${fee['fee_amount']} fee."
            })

        elif days_remaining <= fee["reminder_days"]:
            warnings.append({
                "fee_name": fee["fee_name"],
                "status": "Due Soon",
                "message": f"Payment is due in {days_remaining} day(s)."
            })

    return warnings