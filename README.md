# DataLens AI Backend - Overview 

This is the FastAPI backend for **DataLens AI**, a full-stack AI data analysis application that allows users to create new chats, upload datasets (Provided they can be read by the Pandas library in Python), and ask natural-language questions about their data using Python and Pandas.

The backend handles user authentication, chat session management, message processing, database queries, and API communication with the frontend. Rather than plugging the users' questions directly into the Gemini API, the backend generates and runs Python code, using the Pandas library to conduct data analysis. This was done to hedge against the hallucination of AI models. 

## Features

* User registration and login
* Per-user chat session management
* Create, retrieve, and delete chat sessions
* Send messages to a selected chat
* Store user/chat data in PostgreSQL

## Architecture

Please take a look at the diagram below:

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
* To save tokens, only the user's current message and data set (If applicable) are passed to Gemini. Once rate limting is implemented, I will also include a context window. 

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


## Lessons Learned 
1. This is part of my first full-stack project, so there was naturally a lot for me to learn. During the development and testing of the backend, I had to refine the prompts several times, and even then I had to manipulate Gemini's response in order to produce consistent results. For example, even when I asked it not to return ``` around its response (As its responses are returned in markdown formatting), the model would sometimes do so anyways, meaning I had to programatically strip it off myself. Moreover, I had to consider several scenarios of how to handle certain kinds of input. For example, instead of telling the AI to write Python code for analysis *every* time, I first processed the question as "theoretical", "calculation", or "unrelated", before proceeding to answer the question. In short, I realized that developing AI tools is not as simple as one might expect. This is because you need to learn how to make the model "behave," and still work even when the inputs are unusual.  

2. When I first began the project, I was introduced by a family member to Ollama, a local model runner, and that was I learned that it is actually possible to run AI models relying purely on system resources. This meant that I no longer had to worry about exhausting my API keys, as I stayed on the free tier of the Gemini API. Before using Gemini 2.5 Flash, I used llama3.2 instead, and migrating to Gemini was relatively easy. Likewise, instead of looking for a database provider immediately, I used PgAdmin to create a locally running database, where I learned how to write basic queries before switching to Supabase. Going forward, if I want to build a project that uses AI features, I will continue to use this approach since it is perfect for local development. 

3. In the past, I had browsed through several full stack projects on Github and noticed several patterns that I never understood until I began working on a project myself. In the beginning, I hard coded information such as my database host, port number, user, and password. I had also a dedicated variable to the API key. It was only when I noticed that ".env" is commonly found throughout .gitignore files that I realized I should be moving all of this sensitive information to a file called ".env" that is dedicated to environment variables. Moreover, I learned about the importance of Dockerizing your projects and managing dependencies through a "requirements.txt" file. 