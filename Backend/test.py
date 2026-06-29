import user
from dotenv import load_dotenv
import os
from supabase import create_client, Client

load_dotenv()

url : str = os.getenv("SUPABASE_URL")
key :str = os.getenv("SUPABASE_KEY")
supabase_client : Client = create_client(url, key)

def main():
    returnval = user.signup("shalom test", "sadibos@ilstu.edu", "password")
    print(returnval)
    returnval = user.login("sadibos@ilstu.edu", "password")
    print(returnval)
    user.logout

if __name__ == main():
    main()