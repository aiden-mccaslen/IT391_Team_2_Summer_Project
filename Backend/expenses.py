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
'''
Made account non-nullable in database
made user_id unique so it has to be updated to reflect current balance
'''

def report_expense(access_token, amount, purchase_date, category):
    # caller_client gives us the user's id plus a client that acts as them, so the
    # Row Level Security policy on each table sees an auth.uid() and lets the row
    # through. The shared anonymous client above cannot do that.
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

def report_fund(access_token, amount, account): # can't have checking and saving (need to talk about this)
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
            }, on_conflict="user_id")
            .execute()
        )
        return (True, response.data)

    except Exception as e:
        return (False, str(e))

def get_funds(access_token): # gets income form supabase
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
