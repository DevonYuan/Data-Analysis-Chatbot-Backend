from fastapi import FastAPI, UploadFile, Form
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
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
async def register(username: str = Form(...), password: str = Form(...)):
    if contains_user(username):
        return "Username is taken!"

    cursor.execute("SELECT COUNT(*) FROM users")
    length = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO users (id, username, password) VALUES (%s, %s, %s)",
        (length + 1, username, password),
    )
    connection.commit()
    create_user_folder(username)
    return "Username is now registered!"


@app.post("/delete-user")
async def delete_user(username: str = Form(...)):
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
async def login(username: str = Form(...), password: str = Form(...)):
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    result = cursor.fetchall()
    if len(result) == 1 and username == result[0][1] and password == result[0][2]:
        return "Logged in!"

    return "The password is incorrect, or the user does not exist!"


@app.post("/create-chat")
async def create_chat(username: str = Form(...), title: str = Form(...)):
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
async def delete_chat(username: str = Form(...), title: str = Form(...)):
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
    username: str = Form(...), old_title: str = Form(...), new_title: str = Form(...)
):
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
async def upload_file(file: UploadFile, user: str = Form(...), chat: str = Form(...)):
    result = receive_file(file, user, chat)
    connection.commit()
    return result


@app.post("/send-message")
async def send_message(
    username: str = Form(...),
    title: str = Form(...),
    message: str = Form(...),
    sender: str = Form(...),
):
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
async def get_chats(username: str):
    if not contains_user(username):
        return []

    cursor.execute("SELECT title FROM chats WHERE username = %s", (username,))
    rows = cursor.fetchall()

    # rows is a list of tuples like: [('Chat 1',), ('Chat 2',)]
    return [row[0] for row in rows]


@app.get("/get-messages")
async def get_messages(username: str, title: str):
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
