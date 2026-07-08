from fastapi import FastAPI, Request, UploadFile, Form, Depends
from rate_limiter import rate_limit_ip, rate_limit_user
from fastapi.middleware.cors import CORSMiddleware
from response import receive_file, answer_question
from shared import (
    connection,
    cursor,
    contains_user,
    contains_chat,
    contains_file,
    create_user_folder,
    delete_user_folder,
    empty_bucket,
    hash_password,
    verify_password,
    create_access_token,
    require_current_user,
    generate_verification_token,
    store_verification_token,
    send_verification_email,
    verify_email_token,
    is_user_verified,
)
import os


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return "Nothing to find here!"


@app.delete("/wipe")
def wipe():
    cursor.execute("DELETE FROM users")
    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM chats")
    cursor.execute("DELETE FROM filenames")
    connection.commit()
    empty_bucket()
    return "All data has been removed"


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
):
    # Anti-brute-force: 5 registration attempts per minute per IP
    rate_limit_ip(request, max_requests=5, window_seconds=60, endpoint="register")
    if contains_user(username):
        cursor.execute(
            "SELECT email_verified FROM users WHERE username = %s", (username,)
        )
        result = cursor.fetchone()
        if result and result[0]:
            return "Username is taken!"
        # Unverified user — wipe stale data and allow re-registration
        cursor.execute("DELETE FROM users WHERE username = %s", (username,))
        cursor.execute("DELETE FROM chats WHERE username = %s", (username,))
        cursor.execute("DELETE FROM messages WHERE username = %s", (username,))
        cursor.execute("DELETE FROM filenames WHERE username = %s", (username,))
        connection.commit()
        delete_user_folder(username)

    cursor.execute("SELECT COUNT(*) FROM users")
    length = cursor.fetchone()[0]
    hashed_password = hash_password(password)
    cursor.execute(
        "INSERT INTO users (id, username, password, first_name, last_name) VALUES (%s, %s, %s, %s, %s)",
        (length + 1, username, hashed_password, first_name, last_name),
    )
    connection.commit()
    create_user_folder(username)

    token = generate_verification_token()
    store_verification_token(username, token)
    send_verification_email(username, token)

    return {
        "message": "Account created! Please check your email to verify your account."
    }


@app.post("/delete-user")
async def delete_user(username: str = Depends(require_current_user)):
    if not contains_user(username):
        return "The database does not contain this user!"

    cursor.execute("DELETE FROM users WHERE username = %s", (username,))
    cursor.execute("DELETE FROM chats WHERE username = %s", (username,))
    cursor.execute("DELETE FROM messages WHERE username = %s", (username,))
    cursor.execute("DELETE FROM filenames WHERE username = %s", (username,))
    connection.commit()
    delete_user_folder(username)
    return "The user and their data have been wiped!"


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # Anti-brute-force: 5 login attempts per minute per IP
    rate_limit_ip(request, max_requests=5, window_seconds=60, endpoint="login")
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    result = cursor.fetchall()
    if (
        len(result) == 1
        and username == result[0][1]
        and verify_password(password, result[0][2])
    ):
        if not is_user_verified(username):
            return "Please verify your email before logging in."
        access_token = create_access_token(data={"sub": username})
        return {
            "message": "Logged in!",
            "access_token": access_token,
            "token_type": "bearer",
        }

    return "The password is incorrect, or the user does not exist!"


@app.post("/logout")
async def logout(username: str = Depends(require_current_user)):
    # JWT is stateless, so logout is handled client-side by removing the token.
    # This endpoint exists for consistency and can be extended later.
    return {"message": "Logged out successfully"}


@app.get("/get-user-profile")
async def get_user_profile(username: str = Depends(require_current_user)):
    if not contains_user(username):
        return {"first_name": "", "last_name": ""}

    cursor.execute(
        "SELECT first_name, last_name FROM users WHERE username = %s",
        (username,),
    )
    result = cursor.fetchone()
    if result:
        return {"first_name": result[0], "last_name": result[1]}
    return {"first_name": "", "last_name": ""}


@app.get("/verify-email")
async def verify_email(token: str):
    success, message = verify_email_token(token)
    if success:
        return {"message": "Email verified successfully! You can now log in."}
    return {"message": message}


@app.post("/resend-verification")
async def resend_verification(request: Request, username: str = Form(...)):
    rate_limit_ip(
        request, max_requests=3, window_seconds=300, endpoint="resend-verification"
    )
    cursor.execute("SELECT email_verified FROM users WHERE username = %s", (username,))
    result = cursor.fetchone()
    if not result:
        return "User not found."
    if result[0]:
        return "Email is already verified."

    token = generate_verification_token()
    store_verification_token(username, token)
    send_verification_email(username, token)
    return {"message": "Verification email sent! Please check your inbox."}


@app.post("/create-chat")
async def create_chat(
    request: Request,
    username: str = Depends(require_current_user),
    title: str = Form(...),
):
    # General: 30 requests per minute per IP
    rate_limit_ip(request, max_requests=30, window_seconds=60, endpoint="create-chat")
    if not contains_user(username):
        return "The database does not contain this user!"

    if contains_chat(username, title):
        return "The user already has a chat with this title!"

    cursor.execute(
        "INSERT INTO chats (username, title) VALUES (%s, %s)",
        (username, title),
    )
    connection.commit()
    return "Chat created!"


@app.post("/delete-chat")
async def delete_chat(
    request: Request,
    username: str = Depends(require_current_user),
    title: str = Form(...),
):
    # General: 30 requests per minute per IP
    rate_limit_ip(request, max_requests=30, window_seconds=60, endpoint="delete-chat")
    if not contains_user(username):
        return "The database does not contain this user!"

    if not contains_chat(username, title):
        return "The user does not contain a chat with this title!"

    cursor.execute(
        "DELETE FROM chats WHERE username = %s AND title = %s",
        (username, title),
    )
    cursor.execute(
        "DELETE FROM messages WHERE username = %s AND title = %s",
        (username, title),
    )
    cursor.execute(
        "DELETE FROM filenames WHERE username = %s AND chat = %s",
        (username, title),
    )
    connection.commit()
    return "The chat data has been erased!"


@app.post("/rename-chat")
async def rename_chat(
    request: Request,
    username: str = Depends(require_current_user),
    old_title: str = Form(...),
    new_title: str = Form(...),
):
    # General: 30 requests per minute per IP
    rate_limit_ip(request, max_requests=30, window_seconds=60, endpoint="rename-chat")
    if not contains_user(username):
        return "The database does not contain this user!"
    if not contains_chat(username, old_title):
        return "The user does not have a chat with this title!"
    if contains_chat(username, new_title):
        return "The user already has a chat with the new title!"

    cursor.execute(
        "UPDATE chats SET title = %s WHERE username = %s AND title = %s",
        (new_title, username, old_title),
    )
    cursor.execute(
        "UPDATE messages SET title = %s WHERE username = %s AND title = %s",
        (new_title, username, old_title),
    )
    cursor.execute(
        "UPDATE filenames SET chat = %s WHERE username = %s AND chat = %s",
        (new_title, username, old_title),
    )
    connection.commit()
    return "Chat renamed!"


@app.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile,
    username: str = Depends(require_current_user),
    chat: str = Form(...),
):
    # General: 30 requests per minute per IP
    rate_limit_ip(request, max_requests=30, window_seconds=60, endpoint="upload")
    result = receive_file(file, username, chat)
    connection.commit()
    return result


@app.post("/send-message")
async def send_message(
    request: Request,
    username: str = Depends(require_current_user),
    title: str = Form(...),
    message: str = Form(...),
    sender: str = Form(...),
):
    # AI abuse prevention: 10 AI messages per minute per user
    rate_limit_user(
        username, max_requests=10, window_seconds=60, endpoint="send-message"
    )
    # Also limit by IP as a secondary guard
    rate_limit_ip(request, max_requests=20, window_seconds=60, endpoint="send-message")
    if not contains_user(username):
        return "The database does not contain this user!"

    if not contains_chat(username, title):
        return "The user does not contain a chat with this title!"

    cursor.execute(
        "INSERT INTO messages (username, title, message, sender) VALUES (%s, %s, %s, %s)",
        (username, title, message, sender),
    )
    connection.commit()

    ai_reply = answer_question(username, title, message)
    cursor.execute(
        "INSERT INTO messages (username, title, message, sender) VALUES (%s, %s, %s, %s)",
        (username, title, ai_reply, "AI"),
    )
    connection.commit()
    return ai_reply


@app.get("/get-chats")
async def get_chats(username: str = Depends(require_current_user)):
    if not contains_user(username):
        return []

    cursor.execute("SELECT title FROM chats WHERE username = %s", (username,))
    rows = cursor.fetchall()

    # rows is a list of tuples like: [('Chat 1',), ('Chat 2',)]
    return [row[0] for row in rows]


@app.get("/get-messages")
async def get_messages(username: str = Depends(require_current_user), title: str = ""):
    if not contains_user(username):
        return []

    if not contains_chat(username, title):
        return []

    cursor.execute(
        "SELECT message, sender FROM messages WHERE username = %s AND title = %s",
        (username, title),
    )
    rows = cursor.fetchall()

    return [{"sender": row[1], "text": row[0]} for row in rows]
