from fastapi import UploadFile
from shared import (
    cursor,
    contains_user,
    contains_chat,
    contains_file,
    supabase,
    gemini_client,
)
from pandasai import SmartDataframe
from pandasai.llm.base import LLM
from io import BytesIO
import os
import io
import contextlib
import pandas as pd


class GeminiLLM(LLM):
    def __init__(self, model="gemini-2.5-flash"):
        super().__init__()
        self.model = model

    def call(self, instruction: str, value: str = None, **kwargs) -> str:
        prompt = instruction if value is None else f"{instruction}\n{value}"
        response = gemini_client.interactions.create(
            model=self.model,
            input=prompt,
        )
        return response.output_text


def receive_file(file: UploadFile, user: str, chat_title: str):
    if not contains_user(user) or not contains_chat(user, chat_title):
        return "Either this user does not exist, or this chat does not exist, or both"

    filename = file.filename
    extension = os.path.splitext(filename)[1].lower()
    if extension not in [".csv", ".tsv", ".xlsx"]:
        return "Unsupported file type"

    if contains_file(user, chat_title):
        return "This user has already uploaded a file to this chat"

    file_url = save_uploaded_file(file, user)

    cursor.execute(
        "INSERT INTO filenames (username, chat, filename, file_url) VALUES (%s, %s, %s, %s)",
        (user, chat_title, filename, file_url),
    )
    cursor.connection.commit()

    return file_url


def save_uploaded_file(file: UploadFile, user: str):
    file_bytes = file.file.read()
    path = f"{user}/{file.filename}"

    supabase.storage.from_("user-uploads").upload(path, file_bytes)
    url = supabase.storage.from_("user-uploads").get_public_url(path)
    return url


def answer_question(user: str, chat_title: str, question: str):
    if not contains_user(user):
        return "This user does not exist"

    if not contains_chat(user, chat_title):
        return "The user does not have a chat with this title"

    for _ in range(3):
        prompt = (
            "Classify the following question as 'conceptual', 'calculation', or 'irrelevant'.\n"
            f"{question}\n"
            "Only return one of these exact words with nothing else."
        )

        response = gemini_client.interactions.create(
            model="gemini-2.5-flash",
            input=prompt,
        )
        qtype = response.output_text.strip().lower()

        if qtype == "conceptual":
            return conceptual_question(question)

        if qtype == "calculation":
            return calculation_question(question, user, chat_title)

        if qtype == "irrelevant":
            return irrelevant_question(question)

    return conceptual_question(question)


def conceptual_question(question: str):
    response = gemini_client.interactions.create(
        model="gemini-2.5-flash",
        input=f"Answer the following question conceptually:\n{question}",
    )
    return response.output_text


def calculation_question(question: str, user: str, chat_title: str):
    prompt = (
        "Write Python code using the pandas library to answer the following question:\n"
        f"{question}\n"
        "Your code must:\n"
        "- Use the already-loaded DataFrame named `data`\n"
        "- Print exactly one number using a single print() statement\n"
        "- Include comments explaining each step\n"
        "- Make an educated guess if the question is ambiguous\n"
        "Only return raw Python code with no explanation.\n"
        "Do not surround the code with any markdown formatting"
    )

    data = None

    if contains_file(user, chat_title):
        cursor.execute(
            "SELECT file_url FROM filenames WHERE username = %s AND chat = %s",
            (user, chat_title),
        )
        row = cursor.fetchone()

        if row:
            file_url = row[0]
            extension = os.path.splitext(file_url)[1].lower()

            data = load_dataframe_from_url(file_url, extension)

            prompt += "\n\nHere is the dataset named `data` (string representation):\n"
            prompt += data.to_string()

    for _ in range(5):
        response = gemini_client.interactions.create(
            model="gemini-2.5-flash",
            input=prompt,
        )
        code = response.output_text.strip()

        code = code.replace("```python", "").replace("```", "").strip()
        print(code)

        try:
            result = run_and_capture(code, data)
            return result
        except Exception as e:
            print(f"Execution error for user={user}, chat={chat_title}: {e}")

    if data is not None:
        return pandasai_fallback(data, question)

    return conceptual_question(question)


def load_dataframe_from_url(file_url: str, extension: str):
    path = file_url.split("/user-uploads/")[1]
    file_data = supabase.storage.from_("user-uploads").download(path)
    file_bytes = BytesIO(file_data)

    if extension == ".csv":
        return pd.read_csv(file_bytes)
    elif extension == ".tsv":
        return pd.read_csv(file_bytes, sep="\t")
    elif extension == ".xlsx":
        return pd.read_excel(file_bytes)


def run_and_capture(code_str: str, data: pd.DataFrame | None):
    buffer = io.StringIO()
    sandbox_globals = {"pd": pd}

    if data is not None:
        sandbox_globals["data"] = data

    with contextlib.redirect_stdout(buffer):
        exec(code_str, sandbox_globals)

    return buffer.getvalue()


def irrelevant_question(question: str):
    prompt = (
        "Answer the following question conceptually, and explicitly state that "
        "it is not relevant to the topic of statistics:\n"
        f"{question}"
    )

    response = gemini_client.interactions.create(
        model="gemini-2.5-flash",
        input=prompt,
    )
    return response.output_text


def pandasai_fallback(data: pd.DataFrame, question: str):
    llm = GeminiLLM(model="gemini-2.5-flash")
    sdf = SmartDataframe(data, config={"llm": llm})

    try:
        answer = sdf.chat(question)
        return str(answer)
    except Exception as e:
        return f"PandasAI failed to answer the question: {e}"
