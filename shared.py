from dotenv import load_dotenv
from supabase import create_client
from google import genai
import psycopg2
import os
import bcrypt

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


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))


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


def create_user_folder(username: str):
    folder_path = f"{username}/.keep"
    try:
        supabase.storage.from_("user-uploads").upload(folder_path, b"")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise e


BUCKET_NAME = "user-uploads"


def _collect_bucket_paths(prefix: str = "") -> list[str]:
    bucket = supabase.storage.from_(BUCKET_NAME)
    items = bucket.list(prefix)
    if not items:
        return []

    paths: list[str] = []
    for item in items:
        name = item["name"]
        if name == ".emptyFolderPlaceholder":
            continue

        path = f"{prefix}/{name}" if prefix else name
        if item.get("id") is None:
            paths.extend(_collect_bucket_paths(path))
        else:
            paths.append(path)

    return paths


def delete_user_folder(username: str):
    try:
        paths = _collect_bucket_paths(username)
        if paths:
            supabase.storage.from_(BUCKET_NAME).remove(paths)
    except Exception as e:
        print(f"Error deleting user folder: {e}")


def empty_bucket():
    try:
        paths = _collect_bucket_paths()
        if paths:
            supabase.storage.from_(BUCKET_NAME).remove(paths)
    except Exception as e:
        print(f"Error emptying bucket: {e}")
        raise
