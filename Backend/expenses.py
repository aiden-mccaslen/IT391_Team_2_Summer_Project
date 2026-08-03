from dotenv import load_dotenv
import os
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase_client: Client = create_client(url, key)

def report_expense(access_token, amount, purchase_date, category):
    print("report_expense called")
    try: # This is where I need to save to the database
        print("Before-ID")
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id
        #uuid = user.
        print("After-ID")
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
        return (True, "Expense saved to table")

    except Exception as e:
        return (False, str(e))

def report_fund(access_token, amount, account):
    try: # This is where I need to save to the database
        print("Before-ID")
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id
        #uuid = user.
        print("After-ID")
        response = (
            supabase_client.table("expenses")
            .insert([{
                "user_id": uuid,
                "amount": amount,
                "account": account 
                }
            ]).execute()
        )
        return (True, "Expense saved to table")

    except Exception as e:
        return (False, str(e))