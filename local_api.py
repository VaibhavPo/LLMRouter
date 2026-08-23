"""
local_api.py

FastAPI server exposing your orchestrator as an OpenAI-compatible chat API.
Continue (VS Code) calls this instead of OpenAI's API.

Run with:
    uvicorn local_api:app --host 127.0.0.1 --port 8000

Then configure Continue to use http://127.0.0.1:8000
"""
from fastapi.responses import StreamingResponse
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import json

from orchestrator import Orchestrator

app = FastAPI(title="Local AI Orchestrator API")

# Initialize orchestrator once
orchestrator = Orchestrator()

# OpenAI-compatible message format
class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """OpenAI-compatible chat request format."""
    model: str = "local"
    messages: List[Message]
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class ChatResponse(BaseModel):
    """OpenAI-compatible chat response format."""
    id: str = "local-1"
    object: str = "chat.completion"
    created: int = 0
    model: str = "local"
    choices: List[dict]
    usage: dict


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/models")
def list_models():
    """List available models (for Continue compatibility)."""
    return {
        "data": [
            {
                "id": "local",
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ]
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatRequest):
    """
    OpenAI-compatible chat endpoint. Supports streaming.
    """
    try:
        print("\n=== DEBUG: Chat request received ===")
        
        user_messages = [m for m in request.messages if m.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message found")

        user_message = user_messages[-1].content
        print(f"DEBUG: User message: {user_message}")

        project_id = None
        actual_request = user_message

        if user_message.startswith("project:"):
            lines = user_message.split("\n", 1)
            project_id = lines[0].replace("project:", "").strip()
            actual_request = lines[1] if len(lines) > 1 else ""

        print(f"DEBUG: Calling orchestrator.run()...")
        result = orchestrator.run(
            actual_request,
            project_id=project_id,
            skip_grilling=True,
        )
        
        response_text = result.response or "No response generated."
        if result.context_md:
            response_text += f"\n\n---\n**CONTEXT.md:**\n{result.context_md}"

        print(f"DEBUG: Response length: {len(response_text)}")

        # Check if client wants streaming (Continue often does)
        stream = request.model_dump().get("stream", False)
        
        if stream:
            # Streaming response
            def generate():
                print("DEBUG: Streaming response")
                # Send the full response in one chunk
                chunk = {
                    "id": "local-1",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "local",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": response_text,
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                
                # Send finish chunk
                finish_chunk = {
                    "id": "local-1",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "local",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(finish_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            # Non-streaming response
            print("DEBUG: Non-streaming response")
            return {
                "id": "local-1",
                "object": "chat.completion",
                "created": 0,
                "model": "local",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_text,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            }

    except Exception as e:
        import traceback
        print("\n=== ERROR ===")
        traceback.print_exc()
        print("=== END ERROR ===\n")
        
        return {
            "id": "local-1",
            "object": "chat.completion",
            "created": 0,
            "model": "local",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Error: {str(e)}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

@app.get("/contexts")
def list_contexts():
    """List all stored project contexts (CONTEXT.md)."""
    projects = orchestrator.list_projects()
    return {"projects": projects}


@app.get("/contexts/{project_id}")
def get_context(project_id: str):
    """Retrieve a specific project's CONTEXT.md."""
    context_md = orchestrator.retrieve_context(project_id)
    if not context_md:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return {"project_id": project_id, "context_md": context_md}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)