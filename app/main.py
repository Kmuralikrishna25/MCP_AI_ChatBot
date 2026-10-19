
import os
import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    AIMessageChunk,
    ToolMessage,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_google_genai.chat_models import (
    GoogleAPIError,
    GoogleRateLimitError,
)

from app.graph.builder import build_graph
from app.mcp_client.client import load_mcp_tools


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_chatbot")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not configured.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncPostgresSaver.from_conn_string(
        DATABASE_URL
    ) as checkpointer:
        await checkpointer.setup()

        tools = await load_mcp_tools()

        logger.info(
            "MCP tools loaded: %s",
            [tool.name for tool in tools],
        )

        app.state.checkpointer = checkpointer

        app.state.graph = build_graph(
            checkpointer=checkpointer,
            tools=tools,
        )

        yield


app = FastAPI(
    title="MCP AI Chatbot",
    version="1.2.0",
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: UUID


class ChatResponse(BaseModel):
    response: str
    thread_id: UUID


def get_config(thread_id):
    return {
        "configurable": {
            "thread_id": str(thread_id),
        }
    }


def get_message_text(message):
    content = message.content

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
        )

    return ""


def serialize_messages(messages):
    serialized = []

    for message in messages:
        if isinstance(message, HumanMessage):
            role = "user"

        elif isinstance(message, AIMessage):
            if message.tool_calls:
                continue

            role = "assistant"

        else:
            continue

        text = get_message_text(message)

        if text.strip():
            serialized.append(
                {
                    "role": role,
                    "content": text,
                }
            )

    return serialized


def get_api_error_detail(error):
    if isinstance(error, GoogleRateLimitError):
        return (
            "Gemini API quota exceeded. "
            "Please wait for your quota to reset "
            "or use another model with available quota."
        )

    if isinstance(error, GoogleAPIError):
        return (
            "Gemini API is currently unavailable. "
            "The model may be experiencing high demand. "
            "Please try again later."
        )

    return (
        "Unable to process the chat request. "
        "Please check the FastAPI logs."
    )


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/conversations")
async def list_conversations(request: Request):
    checkpointer = request.app.state.checkpointer
    graph = request.app.state.graph

    thread_ids = set()

    try:
        async for checkpoint in checkpointer.alist(None):
            thread_id = checkpoint.config.get(
                "configurable", {}
            ).get("thread_id")

            if thread_id:
                thread_ids.add(thread_id)

        conversations = []

        for thread_id in thread_ids:
            state = await graph.aget_state(
                get_config(thread_id)
            )

            messages = serialize_messages(
                state.values.get("messages", [])
            )

            if not messages:
                continue

            title = next(
                (
                    message["content"]
                    for message in messages
                    if message["role"] == "user"
                ),
                "New Conversation",
            )

            conversations.append(
                {
                    "thread_id": thread_id,
                    "title": title[:60],
                    "message_count": len(messages),
                    "updated_at": state.created_at or "",
                }
            )

        conversations.sort(
            key=lambda item: item["updated_at"],
            reverse=True,
        )

        return {
            "conversations": conversations
        }

    except Exception:
        logger.exception("Failed to load conversations")

        raise HTTPException(
            status_code=503,
            detail="Unable to load conversation history.",
        )


@app.get("/conversations/{thread_id}")
async def get_conversation(
    thread_id: UUID,
    request: Request,
):
    try:
        state = await request.app.state.graph.aget_state(
            get_config(thread_id)
        )

        if not state.values:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )

        return {
            "thread_id": str(thread_id),
            "messages": serialize_messages(
                state.values.get("messages", [])
            ),
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to load conversation")

        raise HTTPException(
            status_code=503,
            detail="Unable to load conversation.",
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
):
    config = get_config(payload.thread_id)

    try:
        graph = request.app.state.graph

        previous_state = await graph.aget_state(config)

        previous_message_ids = {
            message.id
            for message in previous_state.values.get(
                "messages", []
            )
            if message.id is not None
        }

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=payload.message
                    )
                ]
            },
            config=config,
        )

        new_messages = [
            message
            for message in result["messages"]
            if message.id not in previous_message_ids
        ]

        for message in new_messages:
            if isinstance(message, AIMessage):
                for tool_call in message.tool_calls:
                    logger.info(
                        "MCP tool called: %s",
                        tool_call["name"],
                    )

            elif isinstance(message, ToolMessage):
                logger.info(
                    "MCP tool completed: %s",
                    message.name,
                )

        ai_message = next(
            (
                message
                for message in reversed(result["messages"])
                if isinstance(message, AIMessage)
                and not message.tool_calls
            ),
            None,
        )

        if ai_message is None:
            raise ValueError(
                "No final AI response was generated."
            )

        answer = get_message_text(ai_message)

        if not answer.strip():
            raise ValueError(
                "The AI response is empty."
            )

        return ChatResponse(
            response=answer,
            thread_id=payload.thread_id,
        )

    except GoogleRateLimitError as error:
        logger.warning("Gemini quota exceeded: %s", error)

        raise HTTPException(
            status_code=429,
            detail=get_api_error_detail(error),
        )

    except GoogleAPIError as error:
        logger.warning("Gemini API error: %s", error)

        raise HTTPException(
            status_code=503,
            detail=get_api_error_detail(error),
        )

    except Exception:
        logger.exception("Chat request failed")

        raise HTTPException(
            status_code=503,
            detail="Unable to process the chat request.",
        )


@app.post("/chat/stream")
async def stream_chat(
    payload: ChatRequest,
    request: Request,
):
    graph = request.app.state.graph
    config = get_config(payload.thread_id)

    async def generate():
        try:
            async for chunk, metadata in graph.astream(
                {
                    "messages": [
                        HumanMessage(
                            content=payload.message
                        )
                    ]
                },
                config=config,
                stream_mode="messages",
            ):
                if metadata.get(
                    "langgraph_node"
                ) != "chatbot":
                    continue

                if not isinstance(
                    chunk, AIMessageChunk
                ):
                    continue

                if chunk.tool_call_chunks:
                    continue

                text = get_message_text(chunk)

                if text:
                    yield json.dumps(
                        {
                            "type": "token",
                            "content": text,
                        }
                    ) + "\n"

            yield json.dumps(
                {
                    "type": "done",
                    "thread_id": str(
                        payload.thread_id
                    ),
                }
            ) + "\n"

        except GoogleRateLimitError as error:
            logger.warning(
                "Gemini streaming quota exceeded: %s",
                error,
            )

            yield json.dumps(
                {
                    "type": "error",
                    "message": get_api_error_detail(error),
                }
            ) + "\n"

        except GoogleAPIError as error:
            logger.warning(
                "Gemini streaming API error: %s",
                error,
            )

            yield json.dumps(
                {
                    "type": "error",
                    "message": get_api_error_detail(error),
                }
            ) + "\n"

        except Exception:
            logger.exception("Streaming chat failed")

            yield json.dumps(
                {
                    "type": "error",
                    "message": (
                        "Unable to generate a response. "
                        "Check the FastAPI logs."
                    ),
                }
            ) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
