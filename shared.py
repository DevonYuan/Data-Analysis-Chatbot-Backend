from dotenv import load_dotenv
from supabase import create_client
from google import genai
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
import psycopg2
import os
import bcrypt
import secrets
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

_EMAIL_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "email_templates", "verification_email.html"
)

load_dotenv()

connection = psycopg2.connect(
    host=os.getenv("SUPABASE_HOST"),
    port=int(os.getenv("SUPABASE_PORT_NUMBER")),
    database=os.getenv("SUPABASE_DATABASE"),
    user=os.getenv("SUPABASE_USER"),
    password=os.getenv("SUPABASE_PASSWORD"),
)

connection.autocommit = True
cursor = connection.cursor()

supabase = create_client(
    os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

brevo_api_key = os.getenv("BREVO_API_KEY")
brevo_sender_email = os.getenv("BREVO_SENDER_EMAIL")

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> str | None:
    if token is None:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None


async def require_current_user(token: str = Depends(oauth2_scheme)) -> str:
    username = await get_current_user(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


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


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def store_verification_token(username: str, token: str):
    expires = datetime.utcnow() + timedelta(minutes=10)
    cursor.execute(
        "UPDATE users SET verification_token = %s, verification_token_expires = %s WHERE username = %s",
        (token, expires, username),
    )
    connection.commit()


def _load_email_template() -> str:
    with open(_EMAIL_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def send_verification_email(email: str, token: str):
    frontend_url = os.getenv(
        "FRONTEND_URL", "https://data-analysis-chatbot-frontend.onrender.com"
    )
    verification_link = f"{frontend_url}/verify-email?token={token}"

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = brevo_api_key

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    subject = "Verify your email address"
    html_content = _load_email_template().replace(
        "{{verification_link}}", verification_link
    )
    sender = {"email": brevo_sender_email}
    to = [{"email": email}]

    try:
        api_instance.send_transac_email(
            sib_api_v3_sdk.SendSmtpEmail(
                sender=sender, to=to, subject=subject, html_content=html_content
            )
        )
    except ApiException as e:
        print(f"Exception when calling TransactionalEmailsApi->send_transac_email: {e}")


def verify_email_token(token: str) -> tuple[bool, str | None]:
    cursor.execute(
        "SELECT username, email_verified, verification_token_expires FROM users WHERE verification_token = %s",
        (token,),
    )
    result = cursor.fetchone()

    if not result:
        return False, "Invalid or expired verification token."

    username, email_verified, expires = result

    if email_verified:
        return False, "Email is already verified."

    if datetime.utcnow() > expires:
        return False, "Verification token has expired. Please request a new one."

    cursor.execute(
        "UPDATE users SET email_verified = TRUE, verification_token = NULL, verification_token_expires = NULL WHERE username = %s",
        (username,),
    )
    connection.commit()

    return True, username


def is_user_verified(username: str) -> bool:
    cursor.execute("SELECT email_verified FROM users WHERE username = %s", (username,))
    result = cursor.fetchone()
    return result[0] if result else False
