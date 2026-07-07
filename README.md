# DataLens AI Backend - Overview 

This is the FastAPI backend for **DataLens AI**, a full-stack AI data analysis application that allows users to create new chats, upload datasets (Provided they can be read by the Pandas library in Python), and ask questions about their data.

The backend handles user authentication, chat session management, message processing, database queries, object storage, and API communication with the frontend. Rather than directly having an AI answer the question, instead we ask it to generate and run Python code, using the Pandas library to conduct data analysis. This was done to hedge against the hallucination of AI models. 

## Features

* User registration and login
* Per-user chat session management
* Create, retrieve, and delete chat sessions
* Send messages to a selected chat

Currently in progress: Account deletion 

## Architecture

Please take a look at the diagram below:

```mermaid
flowchart TD
    A[React + Vite Frontend] <--> B[FastAPI Backend]
    B --> C[PostgreSQL on Supabase]
    B --> D[Supabase Bucket Storage]
    B --> E[Gemini API]
    E --> F[Generated Pandas Code]
    F --> G[Analysis Result]
    G --> B
```

## Tech Stack 
**Backend:** FastAPI, Uvicorn (ASGI server), Pandas (Data analysis), PandasAI (AI for pandas), python-jose (JWT based authentication), psycopg2 (Database connection), bcrypt (Hashing passwords), python-multipart (Form data handling), python-dotenv (Environment variables), supabase (Storage and database client), sib-api-v3-sdk (Brevo SDK) <br>
**Frontend:** React + Vite (Javascript), React 3F and Drei (Visuals), React Router, react-markdown (Markdown rendering), remark-gfm (GitHub flavored markdown), three (3D library) <br>
**Deployment:** Docker, Supabase (Bucket storage and PostgreSQL database), Railway (Backend), Render (Frontend) <br>
**Third Party APIs:** Gemini (AI features), Brevo (Sending emails) <br>

**For Local Development:** <br>
- AI features used qwen2.5-coder, running on Ollama 
- A local PostgreSQL database was created with PgAdmin4.


## Security Features
- Encryption 
- JWT based authentication
- Email verification on signup 
- API Rate Limiting 

A security note on the AI generated code: The only context we pass into the AI is the user's question, the chat history, and the dataset, if applicable. The AI does NOT have access to sensitive information such as the user and the environment variables. 