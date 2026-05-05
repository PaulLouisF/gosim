"""
Streams reasoning steps to the frontend via WebSocket.
These are displayed on screen only — never spoken.
"""
from models.schemas import ReasoningStep


async def emit(ws_manager, session_id: str, step_type: str,
               message: str, detail: str = None, status: str = "running"):
    """Send a reasoning step to the frontend WebSocket."""
    step = ReasoningStep(
        type=step_type,
        message=message,
        detail=detail,
        status=status
    )
    await ws_manager.send(session_id, {
        "event": "reasoning",
        "step": step.dict()
    })
