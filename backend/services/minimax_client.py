"""MiniMax client using Anthropic-compatible API (Token Plan)."""
import os
import re
import anthropic


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=os.getenv("MINIMAX_API_KEY"),
        base_url=os.getenv("MINIMAX_API_BASE", "https://api.minimax.io/anthropic"),
    )


async def minimax_complete(prompt: str,
                            system: str = "You are a helpful assistant. Return only valid JSON when asked.",
                            max_tokens: int = 2000,
                            model: str = None,
                            thinking_budget: int = None) -> str:
    """
    thinking_budget:
      None (default) → let the model decide (M2.7 will think)
      0              → try to disable thinking for speed (simple tasks)
      N > 0          → cap thinking at N tokens (quality/speed tradeoff)
    """
    m = model or os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
    client = _client()

    create_kwargs: dict = dict(
        model=m,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    )
    if thinking_budget is not None:
        if thinking_budget > 0:
            create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        else:
            create_kwargs["thinking"] = {"type": "disabled"}

    import asyncio
    loop = asyncio.get_event_loop()

    async def _call():
        try:
            return await loop.run_in_executor(
                None,
                lambda: client.messages.create(**create_kwargs)
            )
        except Exception:
            # If thinking param is rejected, retry without it
            if "thinking" in create_kwargs:
                kw2 = {k: v for k, v in create_kwargs.items() if k != "thinking"}
                return await loop.run_in_executor(
                    None,
                    lambda: client.messages.create(**kw2)
                )
            raise

    response = await _call()

    # M2.7 may return ThinkingBlock(s) before the TextBlock — find the first text block
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()

    # Fallback: thinking consumed all tokens before a TextBlock could be emitted.
    # Extract the usable content from the ThinkingBlock — everything from the first
    # markdown heading onwards is the actual output the model was writing.
    for block in response.content:
        if hasattr(block, "thinking") and block.thinking:
            thinking = block.thinking
            m_heading = re.search(r"^#{1,3} ", thinking, re.MULTILINE)
            if m_heading:
                return thinking[m_heading.start():].strip()
            return thinking.strip()

    raise ValueError(f"No usable content in MiniMax response: {response.content}")


