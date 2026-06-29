# DataLens AI Backend - Overview 

This is the FastAPI backend for **DataLens AI**, a full-stack AI data analysis application that allows users to create analysis chats, upload datasets, and ask natural-language questions about their data using Python and Pandas.

The backend handles user authentication, chat session management, message processing, database queries, and API communication with the frontend. Rather than plugging the users' questions directly into the Gemini API, the backend generates and runs Python code, using the Pandas library to conduct data analysis. This was done to hedge against the hallucination of AI models. 

## Features

* User registration and login
* Per-user chat session management
* Create, retrieve, and delete chat sessions
* Send messages to a selected chat
* Store user/chat data in PostgreSQL

## Architecture

DataLens AI uses a separated frontend/backend architecture.

```txt 
React + Vite Frontend (Deployed on Render)
        |
        | REST API requests
        v
FastAPI Backend (Deployed on Railway)
        |
        v
PostgreSQL Database (Deployed on Supabase) + Supabase Bucket Storage
```


## Current Limitations

This project is still under active development. Some current limitations include:

* Passwords are not yet hashed.
* Some endpoints return plain-text messages instead of structured JSON responses.
* Error handling can be improved with proper HTTP status codes.
* Rate limiting has not yet been implemented.
* Uploaded dataset storage security is still planned for improvement.
* Automated tests have not yet been added.

## Planned Improvements

Planned production-quality improvements include:

* Hashing passwords
* Return structured JSON responses from all endpoints
* Add proper HTTP status codes for errors
* Add request validation with Pydantic models
* Add API rate limiting
* Add private file storage and signed URLs
* Add token usage tracking for AI requests
* Add conversation context management
* Add automated backend tests
* Add CI/CD checks before deployment
