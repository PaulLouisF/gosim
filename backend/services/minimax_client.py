"""MiniMax client using Anthropic-compatible API (Token Plan)."""
import os
import anthropic


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=os.getenv("MINIMAX_API_KEY"),
        base_url=os.getenv("MINIMAX_API_BASE", "https://api.minimax.io/anthropic"),
    )


async def minimax_complete(prompt: str,
                            system: str = "You are a helpful assistant. Return only valid JSON when asked.",
                            max_tokens: int = 1000,
                            model: str = None) -> str:
    m = model or os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
    client = _client()
    # Anthropic SDK is sync; run in thread to stay non-blocking
    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.messages.create(
            model=m,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
    )
    # M2.7 may return ThinkingBlock(s) before the TextBlock — find the first text block
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise ValueError(f"No text block in MiniMax response: {response.content}")
