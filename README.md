# MCP AI Chatbot

A conversational assistant with a Streamlit chat interface and a FastAPI backend. The backend uses Google Gemini with LangGraph, calls tools from a local Model Context Protocol (MCP) server, and saves conversations in PostgreSQL.

## Features

- Stream assistant responses as they are generated.
- Start conversations and return to previously saved chats.
- Use Gemini and LangGraph to route questions to MCP tools.
- Search the web and webpages with Tavily.
- Get current weather, Wikipedia summaries, calculations, and UTC time.
- Search for flights using the Duffel integration.

## Project structure

```text
.
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application and API routes
│   ├── static/
│   │   ├── components.html     # HTML fragments used by the Streamlit UI
│   │   └── style.css           # Streamlit UI styles
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── builder.py          # LangGraph workflow
│   │   ├── nodes.py            # Gemini chatbot node and instructions
│   │   └── state.py            # Conversation state
│   └── mcp_client/
│       ├── __init__.py
│       └── client.py           # Starts the local MCP server and loads tools
├── mcp_server/
│   ├── __init__.py
│   ├── server.py               # MCP server and tool definitions
│   └── tools/
│       ├── __init__.py
│       └── duffel_tools.py     # Duffel flight-search tool
├── .env                        # Local secrets and configuration (not committed)
├── .gitignore
├── .dockerignore                # Files excluded from Docker build context
├── .env.example                 # Docker environment template
├── Dockerfile                   # Backend and Streamlit image targets
├── docker-compose.yml           # Streamlit, FastAPI, and PostgreSQL services
├── main.py                     # Standalone starter; not the chatbot entry point
├── pyproject.toml              # Project metadata and dependencies
├── README.md
├── requirements.txt            # Partial dependency list
└── streamlit_app.py            # Streamlit user interface
```

## Requirements

- Python 3.11 or newer.
- PostgreSQL, accessible by the application.
- A Google Gemini API key.
- A Tavily API key for web search and webpage extraction.
- A Duffel access token for flight search.

## Setup

From the project directory, create and activate a virtual environment in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the dependencies declared in `pyproject.toml`:

```powershell
python -m pip install `
  "fastapi>=0.143.0" `
  "httpx>=0.28.1" `
  "langchain-google-genai>=4.4.0" `
  "langchain-mcp-adapters>=0.3.2" `
  "langgraph>=1.2.9" `
  "langgraph-checkpoint-postgres>=3.1.2" `
  "mcp[cli]>=1.30.0" `
  "psycopg[binary,pool]>=3.3.5" `
  "python-dotenv>=1.2.3" `
  "streamlit>=1.64.0" `
  "tavily-python>=0.8.5" `
  "uvicorn[standard]>=0.54.0"
```

Create a `.env` file in the project root and set the required values:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
TAVILY_API_KEY=your_tavily_api_key
DUFFEL_ACCESS_TOKEN=your_duffel_access_token

# Optional
GEMINI_MODEL=gemini-3.8-flash
DUFFEL_BASE_URL=https://api.duffel.com
BACKEND_URL=http://127.0.0.1:8000
```

`GEMINI_API_KEY` and `DATABASE_URL` are required to start the backend. `TAVILY_API_KEY` enables Tavily tools, and `DUFFEL_ACCESS_TOKEN` is used by the flight-search integration. Keep credentials private; `.env` is ignored by Git.

## Run

Start the backend from the project root:

```powershell
python -m uvicorn app.main:app --reload
```

In a second PowerShell window, activate the same virtual environment and start the interface:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run streamlit_app.py
```

Open the Streamlit URL shown in the terminal (typically `http://localhost:8501`). The backend listens at `http://127.0.0.1:8000` by default. Set `BACKEND_URL` if the backend is hosted elsewhere.

## Run with Docker

The Docker setup runs the Streamlit UI, FastAPI backend, MCP tools, and PostgreSQL in separate services. Docker Compose builds the backend and UI from separate targets in the same `Dockerfile`; the backend starts the MCP server as a subprocess and receives a `DATABASE_URL` pointing to the Compose PostgreSQL service.

1. Copy the environment template and fill in the required Gemini key and a strong PostgreSQL password. Add optional integration keys to enable Tavily and Duffel tools:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set `POSTGRES_PASSWORD` to a URL-safe value (letters, numbers, hyphens, and underscores are suitable) because Compose uses it in `DATABASE_URL`. Do not commit `.env`.

2. Build and start the services from the project directory:

   ```powershell
   docker compose up --build
   ```

3. Open the Streamlit interface at `http://localhost:8501`. The backend API is available at `http://localhost:8000/docs`.

PostgreSQL data is stored in the `postgres_data` Docker volume and remains available when containers are recreated. To stop the services while keeping the data, run `docker compose down`. To also delete the saved conversation database, run `docker compose down --volumes`.

## Backend API

All routes are served by the FastAPI app in `app/main.py`. Open `http://127.0.0.1:8000/docs` for interactive API documentation.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Check backend health |
| `GET` | `/conversations` | List saved conversations |
| `GET` | `/conversations/{thread_id}` | Load a conversation by UUID |
| `POST` | `/chat` | Send a message and receive a complete response |
| `POST` | `/chat/stream` | Send a message and receive newline-delimited JSON stream events |

Chat requests use a UUID `thread_id`; reuse the same ID to continue a conversation. A request body looks like:

```json
{
  "message": "What is 12 multiplied by 8?",
  "thread_id": "a-valid-uuid"
}
```

The streaming endpoint emits `token` events while generating a response, followed by a `done` event. If generation fails, it emits an `error` event.

## Notes

- `requirements.txt` does not currently list every dependency in `pyproject.toml`; the installation command above uses the full project dependency list.
- The root `main.py` is a starter script and does not launch the chatbot. Use `app.main:app` for the backend and `streamlit_app.py` for the UI.
- The API does not define a `/` route. Use `/docs` for the backend documentation and the Streamlit URL for the chat interface.
