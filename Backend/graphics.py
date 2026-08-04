from dotenv import load_dotenv
import os
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase_client: Client = create_client(url, key)

def getGraphData(access_token):
    try:
        user_response = supabase_client.auth.get_user(access_token)
        uuid = user_response.user.id

        response = (
            supabase_client.table("expenses")
            .select("amount, category, purchase_date")
            .eq("user_id", uuid)
            .execute()
        )
        print(response.data)
        return (True, response.data)

    except Exception as e:
        return (False, str(e))