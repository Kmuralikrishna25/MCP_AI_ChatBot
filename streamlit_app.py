
import json
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv


load_dotenv()

API_BASE_URL = os.getenv(
    "BACKEND_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "app" / "static"
FLIGHT_SAMPLE_DATE = (date.today() + timedelta(days=30)).isoformat()

TOOL_GROUPS = {
    "Web & knowledge": [
        (
            "web_search",
            "Find recent information, news, and facts on the web.",
            "Search the web for recent developments in AI.",
        ),
        (
            "fetch_webpage",
            "Extract readable content from a public HTTPS page.",
            "Summarize this webpage: https://www.python.org/",
        ),
        (
            "search_wikipedia",
            "Find a Wikipedia article and provide its summary.",
            "Find a Wikipedia summary of the history of Python.",
        ),
        (
            "get_weather",
            "Get current weather conditions for a city.",
            "What's the current weather in Tokyo?",
        ),
    ],
    "Travel & maps": [
        (
            "search_flights",
            "Search one-way flights by airport, date, and cabin.",
            f"Find economy flights from SFO to JFK on {FLIGHT_SAMPLE_DATE}.",
        ),
        (
            "geocode_location",
            "Find the coordinates and full address of a place.",
            "Find the coordinates of the Eiffel Tower.",
        ),
        (
            "get_directions",
            "Get driving distance and estimated time between places.",
            "How far is the drive from San Francisco to San Jose?",
        ),
        (
            "search_nearby_places",
            "Find nearby restaurants, hotels, cafes, hospitals, or attractions.",
            "Find cafes near Times Square in New York.",
        ),
    ],
    "Utilities": [
        (
            "calculate",
            "Perform addition, subtraction, multiplication, or division.",
            "Calculate 248 divided by 4.",
        ),
        (
            "convert_currency",
            "Convert an amount between currencies using the latest rate.",
            "Convert 100 USD to EUR.",
        ),
        (
            "get_current_time",
            "Get the current date and time in UTC.",
            "What is the current UTC time?",
        ),
    ],
}


st.set_page_config(
    page_title="MCP AI Chatbot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_css():
    css_path = STATIC_DIR / "style.css"

    if not css_path.is_file():
        st.error(f"CSS file not found: {css_path}")
        return

    css = css_path.read_text(encoding="utf-8")

    st.markdown(
        f"<style>{css}</style>",
        unsafe_allow_html=True,
    )


def render_html(section):
    html_path = STATIC_DIR / "components.html"

    if not html_path.is_file():
        st.error(f"HTML file not found: {html_path}")
        return

    content = html_path.read_text(encoding="utf-8")

    start_marker = f"<!-- START: {section} -->"
    end_marker = f"<!-- END: {section} -->"

    if start_marker not in content or end_marker not in content:
        st.error(f"HTML section not found: {section}")
        return

    section_html = content.split(
        start_marker, 1
    )[1].split(end_marker, 1)[0].strip()

    st.markdown(
        section_html,
        unsafe_allow_html=True,
    )


def api_client():
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=10.0,
            read=180.0,
            write=30.0,
            pool=10.0,
        )
    )


def new_conversation():
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.chat_error = None


def load_conversation(thread_id):
    with api_client() as client:
        response = client.get(
            f"{API_BASE_URL}/conversations/{thread_id}"
        )
        response.raise_for_status()
        data = response.json()

    st.session_state.thread_id = data["thread_id"]
    st.session_state.messages = data["messages"]
    st.session_state.chat_error = None


def get_conversations():
    with api_client() as client:
        response = client.get(
            f"{API_BASE_URL}/conversations"
        )
        response.raise_for_status()
        return response.json().get("conversations", [])


def backend_connected():
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                f"{API_BASE_URL}/health"
            )
            response.raise_for_status()

            return (
                response.json().get("status") == "healthy"
            )

    except (httpx.HTTPError, ValueError):
        return False


def format_http_error(error):
    try:
        detail = error.response.json().get(
            "detail",
            error.response.text,
        )

    except (ValueError, AttributeError):
        detail = error.response.text

    return (
        f"Backend error (HTTP "
        f"{error.response.status_code}): {detail}"
    )


def stream_response(message):
    payload = {
        "message": message,
        "thread_id": st.session_state.thread_id,
    }

    with api_client() as client:
        with client.stream(
            "POST",
            f"{API_BASE_URL}/chat/stream",
            json=payload,
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines():
                if not line:
                    continue

                event = json.loads(line)
                event_type = event.get("type")

                if event_type == "token":
                    yield event.get("content", "")

                elif event_type == "error":
                    raise RuntimeError(
                        event.get(
                            "message",
                            "AI response failed.",
                        )
                    )

                elif event_type == "done":
                    return


load_css()

if "thread_id" not in st.session_state:
    new_conversation()

if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_error" not in st.session_state:
    st.session_state.chat_error = None

if "suggested_prompt" not in st.session_state:
    st.session_state.suggested_prompt = None


connected = backend_connected()


with st.sidebar:
    render_html("sidebar-brand")

    if st.button(
        "＋ New Chat",
        type="primary",
        width="stretch",
    ):
        new_conversation()
        st.rerun()

    st.markdown(
        '<div class="sidebar-section">Navigation</div>',
        unsafe_allow_html=True,
    )

    if st.button(
        "⌂ Home",
        width="stretch",
    ):
        new_conversation()
        st.rerun()

    st.markdown(
        '<div class="sidebar-section">Recent Chats</div>',
        unsafe_allow_html=True,
    )

    try:
        conversations = get_conversations()

        if not conversations:
            st.caption("No saved conversations yet.")

        for conversation in conversations:
            thread_id = conversation["thread_id"]
            title = conversation["title"]

            is_active = (
                thread_id == st.session_state.thread_id
            )

            label = (
                f"● {title}"
                if is_active
                else f"◌ {title}"
            )

            if st.button(
                label,
                key=f"conversation_{thread_id}",
                width="stretch",
            ):
                try:
                    load_conversation(thread_id)
                    st.rerun()

                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                ) as error:
                    st.error(
                        f"Could not load conversation: {error}"
                    )

    except httpx.HTTPError:
        st.warning(
            "Unable to load previous chats. "
            "Check the backend connection."
        )

    except (ValueError, KeyError):
        st.warning(
            "The conversation list is invalid."
        )

    with st.expander("Explore tools", expanded=False):
        st.caption(
            "Choose a tool to send a sample request in chat."
        )

        for group, tools in TOOL_GROUPS.items():
            st.markdown(
                f'<div class="tool-group-title">{group}</div>',
                unsafe_allow_html=True,
            )

            for tool_name, description, sample_prompt in tools:
                st.markdown(
                    f'<div class="tool-card">'
                    f'<div class="tool-name">{tool_name}</div>'
                    f'<div class="tool-description">{description}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if st.button(
                    f"Try {tool_name}",
                    key=f"try_tool_{tool_name}",
                    width="stretch",
                ):
                    st.session_state.suggested_prompt = sample_prompt
                    st.rerun()

    st.markdown(
        '<div class="sidebar-section">System Status</div>',
        unsafe_allow_html=True,
    )

    if connected:
        st.markdown(
            """
            <div class="backend-status">
                <span class="status-dot"></span>
                Backend Connected
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:
        st.markdown(
            """
            <div class="backend-status offline">
                <span class="status-dot"></span>
                Backend Disconnected
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="thread-info">Current Thread ID</div>',
        unsafe_allow_html=True,
    )

    st.code(st.session_state.thread_id)

    render_html("sidebar-footer")


render_html("topbar")


if not st.session_state.messages:
    render_html("welcome")

    st.markdown(
        '<div class="suggestions-label">Explore What I Can Do</div>',
        unsafe_allow_html=True,
    )

    suggestions = [
        (
            "✦ Personal Project",
            "Help me plan a new AI project.",
        ),
        (
            "✉ Generate an Email",
            "Help me write a professional email.",
        ),
        (
            "▤ Summarize",
            "Explain how you can summarize information.",
        ),
        (
            "☼ Creative Brainstorm",
            "Help me brainstorm innovative AI ideas.",
        ),
        (
            "◈ Learn Something New",
            "Teach me an interesting concept in AI.",
        ),
        (
            "◇ Solve a Problem",
            "Help me solve a programming problem.",
        ),
    ]

    for start in range(0, len(suggestions), 3):
        columns = st.columns(3, gap="small")

        for column, (label, message) in zip(
            columns,
            suggestions[start:start + 3],
        ):
            with column:
                if st.button(
                    label,
                    key=f"suggestion_{start}_{label}",
                    width="stretch",
                ):
                    st.session_state.suggested_prompt = message


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


if st.session_state.chat_error:
    st.warning(st.session_state.chat_error)


typed_prompt = st.chat_input(
    "Ask me anything..."
)

suggested_prompt = st.session_state.suggested_prompt
st.session_state.suggested_prompt = None

prompt = typed_prompt or suggested_prompt


if prompt:
    st.session_state.chat_error = None

    st.session_state.messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""

        try:
            with st.spinner("Thinking..."):
                for token in stream_response(prompt):
                    full_response += token
                    placeholder.markdown(
                        full_response + "▌"
                    )

            if not full_response.strip():
                raise RuntimeError(
                    "The backend returned an empty response."
                )

            placeholder.markdown(full_response)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": full_response,
                }
            )

        except httpx.HTTPStatusError as error:
            st.session_state.chat_error = (
                format_http_error(error)
            )
            placeholder.error(
                st.session_state.chat_error
            )

        except httpx.TimeoutException:
            st.session_state.chat_error = (
                "The request timed out. "
                "Check the FastAPI logs."
            )
            placeholder.error(
                st.session_state.chat_error
            )

        except httpx.RequestError:
            st.session_state.chat_error = (
                "Unable to connect to the backend."
            )
            placeholder.error(
                st.session_state.chat_error
            )

        except (
            RuntimeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ) as error:
            st.session_state.chat_error = str(error)
            placeholder.error(
                st.session_state.chat_error
            )
