from dotenv import load_dotenv
import os
from supabase import create_client, Client
import user as user_file

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase_client: Client = create_client(url, key)
# NOTE: supabase_client is anonymous. It is fine for reads/writes that do not go
# through Row Level Security, but every table query below must use the per-user
# client from user.client_for_token() instead -- see the note in that function.
# An anonymous client has no auth.uid(), so RLS rejects the insert outright.

def report_expense(access_token, amount, purchase_date, category):
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    try:
        response = (
            db.table("expenses")
            .insert([{
                "user_id": uuid,
                "amount": amount,
                "purchase_date": purchase_date,
                "category": category 
                }
            ]).execute()
        )
        return (True, response.data)

    except Exception as e:
        return (False, str(e))

def get_expenses(access_token): #gets expenses form supabase
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    try:

        response = (
            db.table("expenses")
            .select("*")
            .eq("user_id", uuid)
            .execute()
        )

        return (True, response.data)

    except Exception as e:
        return (False, str(e))
    
def report_fund(access_token, amount, account): 
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    try:

        response = (
            db.table("funds")
            .upsert({
                "user_id": uuid,
                "amount": amount,
                "account": account
            }, on_conflict="user_id,account") 
            .execute()
        )
        return (True, response.data)

    except Exception as e:
        return (False, str(e))

def get_balance(access_token): # gets income form supabase
    uuid, db = user_file.caller_client(access_token)
    if uuid is None:
        return (False, db)

    try:

        response = (
            db.table("funds")
            .select("*")
            .eq("user_id", uuid)
            .execute()
        )

        return (True, response.data)

    except Exception as e:
        return (False, str(e))

def _split_funds(funds_data):
# funds_data holds one row per account ("checking", "savings")
    checking = 0.0
    savings = 0.0
    for fund in funds_data:
        if fund["account"] == "checking":
            checking = float(fund["amount"])
        elif fund["account"] == "savings":
            savings = float(fund["amount"])
    return checking, savings