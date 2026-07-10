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
import sys
import logging
import json
import base64
import numpy as np

# Configure logging to write to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('debug.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

logger.info("response.py module loaded")
logger.info(f"stdout is redirected: {sys.stdout.name}")


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
    if extension not in [".csv", ".tsv", ".xlsx", ".xls", ".txt", ".json", ".parquet", ".feather"]:
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
    logger.info(f"answer_question called for user={user}, chat={chat_title}")
    if not contains_user(user):
        return "This user does not exist"

    if not contains_chat(user, chat_title):
        return "The user does not have a chat with this title"

    # Get chat messages ordered by id
    cursor.execute(
        "SELECT message FROM messages WHERE username = %s AND title = %s",
        (user, chat_title),
    )
    chat_messages = [row[0] for row in cursor.fetchall()]

    # Check if file exists and load its content
    file_content = ""
    if contains_file(user, chat_title):
        # Load file URL
        cursor.execute(
            "SELECT file_url FROM filenames WHERE username = %s AND chat = %s",
            (user, chat_title),
        )
        row = cursor.fetchone()
        if row:
            file_url = row[0]
            extension = os.path.splitext(file_url)[1].lower()
            # Load dataframe
            data = load_dataframe_from_url(file_url, extension)
            file_content = "Columns: " + ", ".join(data.columns.tolist())

    # Build context parts
    context_parts = []
    if chat_messages:
        context_parts.append("Chat history:")
        for msg in chat_messages:
            context_parts.append(f"User: {msg}")
    if file_content:
        context_parts.append("Dataset:")
        context_parts.append(file_content)

    context = "\n".join(context_parts)

    # Estimate tokens (approx word count)
    def estimate_tokens(text):
        return len(text.split())

    max_tokens = 6000
    # Include question tokens
    current_tokens = estimate_tokens(context) + estimate_tokens(question)

    # Trim oldest messages if needed
    while current_tokens > max_tokens and chat_messages:
        # Remove the oldest message
        chat_messages.pop(0)
        # Rebuild context without that message
        context_parts = []
        if chat_messages:
            context_parts.append("Chat history:")
            for msg in chat_messages:
                context_parts.append(f"User: {msg}")
        if file_content:
            context_parts.append("Dataset:")
            context_parts.append(file_content)
        context = "\n".join(context_parts)
        current_tokens = estimate_tokens(context) + estimate_tokens(question)

    final_context = "\n".join(context_parts)

    # Build classification prompt
    classification_prompt = (
        f"Given the following context (total tokens: {estimate_tokens(final_context)}):\n"
        f"{final_context}\n\n"
        "Classify the following question as 'conceptual', 'calculation', or 'irrelevant'.\n"
        f"Question:\n{question}\n"
        "Only return one of these exact words with nothing else."
    )

    response = gemini_client.interactions.create(
        model="gemini-2.5-flash",
        input=classification_prompt,
    )
    qtype = response.output_text.strip().lower()
    logger.info(f"Question classified as: {qtype}")

    if qtype == "conceptual":
        logger.info("Taking conceptual path")
        return conceptual_question(question, final_context)
    if qtype == "calculation":
        logger.info("Taking calculation path")
        return calculation_question(question, user, chat_title, final_context)
    if qtype == "irrelevant":
        logger.info("Taking irrelevant path")
        return irrelevant_question(question, final_context)
    # fallback
    logger.info("Taking fallback conceptual path")
    return conceptual_question(question, final_context)


def conceptual_question(question: str, context: str = ""):
    prompt = f"Given the following context:\\n{context}\\n\\nAnswer the following question conceptually:\\n{question}"
    response = gemini_client.interactions.create(
        model="gemini-2.5-flash",
        input=prompt,
    )
    return response.output_text


def calculation_question(question: str, user: str, chat_title: str, context: str = ""):
    logger.info(f"calculation_question called for user={user}, chat={chat_title}")
    # Load data if file exists (same as before)
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
            logger.info(f"Data loaded successfully, shape: {data.shape}")

    # Build prompt with context
    prompt = (
        "Given the following conversation history and dataset:\\n"
        f"{context}\\n"
        "Question:\\n"
        f"{question}\\n"
        "Write Python code using the pandas library to answer the following question:\\n"
        "- Use the already-loaded DataFrame named `data`\\n"
        "- Print exactly one number using a single print() statement\\n"
        "- Include comments explaining each step\\n"
        "- Make an educated guess if the question is ambiguous\\n"
        "Only return raw Python code with no explanation.\\n"
        "Do not surround the code with any markdown formatting"
    )

    for _ in range(5):
        response = gemini_client.interactions.create(
            model="gemini-2.5-flash",
            input=prompt,
        )
        code = response.output_text.strip()

        code = code.replace("```python", "").replace("```", "").strip()

        try:
            result = run_and_capture(code, data)
            logger.info(f"Generated code:\n{code}")
            return result
        except Exception as e:
            logger.error(f"Execution error for user={user}, chat={chat_title}: {e}")

    if data is not None:
        return pandasai_fallback(data, question)

    return conceptual_question(question, context)


def load_dataframe_from_url(file_url: str, extension: str):
    path = file_url.split("/user-uploads/")[1]
    file_data = supabase.storage.from_("user-uploads").download(path)
    file_bytes = BytesIO(file_data)

    if extension == ".csv":
        return pd.read_csv(file_bytes)
    elif extension == ".tsv":
        return pd.read_csv(file_bytes, sep="\t")
    elif extension == ".xlsx" or extension == ".xls":
        return pd.read_excel(file_bytes)
    elif extension == ".txt":
        return pd.read_csv(file_bytes, sep="\s+")
    elif extension == ".json":
        return pd.read_json(file_bytes)
    elif extension == ".parquet":
        return pd.read_parquet(file_bytes)
    elif extension == ".feather":
        return pd.read_feather(file_bytes)


def run_and_capture(code_str: str, data: pd.DataFrame | None):
    buffer = io.StringIO()
    sandbox_globals = {"pd": pd}

    if data is not None:
        sandbox_globals["data"] = data

    with contextlib.redirect_stdout(buffer):
        exec(code_str, sandbox_globals)

    return buffer.getvalue()


def irrelevant_question(question: str, context: str = ""):
    prompt = (
        "Given the following context:\\n"
        f"{context}\\n\\n"
        "Answer the following question conceptually, and explicitly state that "
        "it is not relevant to the topic of statistics:\\n"
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


def generate_graph_data(user: str, chat_title: str, graph_type: str = "histogram", column: str = None):
    """Generate graph data for visualization"""
    logger.info(f"generate_graph_data called for user={user}, chat={chat_title}, graph_type={graph_type}")
    
    if not contains_file(user, chat_title):
        return {"error": "No file uploaded for this chat"}
    
    # Load file URL
    cursor.execute(
        "SELECT file_url FROM filenames WHERE username = %s AND chat = %s",
        (user, chat_title),
    )
    row = cursor.fetchone()
    if not row:
        return {"error": "File not found"}
    
    file_url = row[0]
    extension = os.path.splitext(file_url)[1].lower()
    data = load_dataframe_from_url(file_url, extension)
    
    if data is None:
        return {"error": "Failed to load data"}
    
    # Get first column if none specified
    if column is None:
        column = data.columns[0]
    
    # Ensure column exists
    if column not in data.columns:
        return {"error": f"Column '{column}' not found in data"}
    
    # Generate graph data based on type
    try:
        if graph_type == "histogram":
            return generate_histogram_data(data, column)
        elif graph_type == "scatter":
            return generate_scatter_data(data, column)
        elif graph_type == "bar":
            return generate_bar_data(data, column)
        elif graph_type == "line":
            return generate_line_data(data, column)
        else:
            return generate_histogram_data(data, column)
    except Exception as e:
        logger.error(f"Error generating graph data: {e}")
        return {"error": str(e)}


def generate_histogram_data(data: pd.DataFrame, column: str):
    """Generate histogram data for a column"""
    # Get numeric data
    col_data = data[column].dropna()
    
    # Try to convert to numeric if possible
    try:
        col_data = pd.to_numeric(col_data)
    except:
        # If not numeric, use value counts for categorical data
        value_counts = col_data.value_counts()
        return {
            "type": "bar",
            "data": {
                "x": value_counts.index.tolist(),
                "y": value_counts.values.tolist(),
                "type": "bar"
            },
            "layout": {
                "title": f"Distribution of {column}",
                "xaxis": {"title": column},
                "yaxis": {"title": "Count"}
            }
        }
    
    # For numeric data, create histogram
    import numpy as np
    hist, bin_edges = np.histogram(col_data, bins=20)
    
    # Use bin centers for x values
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    
    return {
        "type": "histogram",
        "data": {
            "x": col_data.tolist(),
            "type": "histogram",
            "nbinsx": 20,
            "name": column
        },
        "layout": {
            "title": f"Distribution of {column}",
            "xaxis": {"title": column},
            "yaxis": {"title": "Frequency"}
        }
    }


def generate_scatter_data(data: pd.DataFrame, column: str):
    """Generate scatter plot data - use first numeric column vs second numeric column"""
    numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
    
    if len(numeric_cols) < 2:
        # Fall back to histogram if not enough numeric columns
        return generate_histogram_data(data, column)
    
    x_col = numeric_cols[0]
    y_col = numeric_cols[1] if len(numeric_cols) > 1 else numeric_cols[0]
    
    return {
        "type": "scatter",
        "data": {
            "x": data[x_col].dropna().tolist(),
            "y": data[y_col].dropna().tolist(),
            "mode": "markers",
            "type": "scatter",
            "name": f"{x_col} vs {y_col}"
        },
        "layout": {
            "title": f"{x_col} vs {y_col}",
            "xaxis": {"title": x_col},
            "yaxis": {"title": y_col}
        }
    }


def generate_bar_data(data: pd.DataFrame, column: str):
    """Generate bar chart data using value counts"""
    value_counts = data[column].value_counts().head(20)
    
    return {
        "type": "bar",
        "data": {
            "x": value_counts.index.tolist(),
            "y": value_counts.values.tolist(),
            "type": "bar"
        },
        "layout": {
            "title": f"Count of {column}",
            "xaxis": {"title": column},
            "yaxis": {"title": "Count"}
        }
    }


def generate_line_data(data: pd.DataFrame, column: str):
    """Generate line chart data - assumes data is ordered or uses index"""
    col_data = data[column].dropna()
    
    try:
        col_data = pd.to_numeric(col_data)
    except:
        return generate_bar_data(data, column)
    
    return {
        "type": "line",
        "data": {
            "x": list(range(len(col_data))),
            "y": col_data.tolist(),
            "mode": "lines",
            "type": "scatter"
        },
        "layout": {
            "title": f"{column} over index",
            "xaxis": {"title": "Index"},
            "yaxis": {"title": column}
        }
    }
