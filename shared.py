from dotenv import load_dotenv
from supabase import create_client
from google import genai
import psycopg2
import os

load_dotenv()

connection = psycopg2.connect(
    host=os.getenv("SUPABASE_HOST"),
    port=int(os.getenv("SUPABASE_PORT_NUMBER")),
    database=os.getenv("SUPABASE_DATABASE"),
    user=os.getenv("SUPABASE_USER"),
    password=os.getenv("SUPABASE_PASSWORD"),
)
cursor = connection.cursor()

supabase = create_client(
    os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def contains_user(username: str) -> bool:
    cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
    return cursor.fetchone() is not None


def contains_chat(username: str, title: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM chats WHERE username = %s AND title = %s",
        (username, title),
    )
    return cursor.fetchone() is not None


def contains_file(username: str, chat: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM filenames WHERE username = %s AND chat = %s",
        (username, chat),
    )
    return cursor.fetchone() is not None
