from dotenv import load_dotenv
import os
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase_client: Client = create_client(url, key)

def report_expense(access_token, amount, purchase_date, category):
    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id
        response = (
            supabase_client.table("expenses")
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
    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id

        response = (
            supabase_client.table("expenses")
            .select("*")
            .eq("user_id", uuid)
            .execute()
        )

        return (True, response.data)

    except Exception as e:
        return (False, str(e))
    
def report_fund(access_token, amount, account): 
    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id

        response = (
            supabase_client.table("funds")
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
    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id

        response = (
            supabase_client.table("funds")
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