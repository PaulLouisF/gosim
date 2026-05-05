"""GLM via R9S (Route Tokens) endpoint (OpenAI-compatible)."""
import os
from openai import AsyncOpenAI


def _client():
    return AsyncOpenAI(
        api_key=os.getenv("ZAI_API_KEY"),
        base_url=os.getenv("ZAI_API_BASE", "https://api.r9s.ai/v1")
    )


async def zai_complete(prompt: str,
                        system: str = "You are a helpful assistant.",
                        max_tokens: int = 500,
                        temperature: float = 0.3) -> str:
    model = os.getenv("ZAI_MODEL", "glm-5.1")
    resp = await _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
        temperature=temperature
    )
    return resp.choices[0].message.content.strip()


async def zai_stream(prompt: str, system: str = "You are a helpful assistant."):
    """Stream tokens for low-latency TTS."""
    model = os.getenv("ZAI_MODEL", "glm-5.1")
    stream = await _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        max_tokens=200,
        stream=True
    )
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
