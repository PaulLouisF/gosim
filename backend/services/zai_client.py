"""GLM via R9S (Route Tokens) endpoint (OpenAI-compatible)."""
import re
import os
from openai import AsyncOpenAI


def _client():
    return AsyncOpenAI(
        api_key=os.getenv("ZAI_API_KEY"),
        base_url=os.getenv("ZAI_API_BASE", "https://api.r9s.ai/v1")
    )


def _strip_thinking(text: str) -> str:
    """Remove chain-of-thought / thinking blocks from GLM output."""
    if not text:
        return ""
    # Remove complete <think>...</think> XML blocks
    text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text, flags=re.DOTALL)
    # Remove unclosed <think> blocks (model cut off mid-reasoning — discard rest)
    text = re.sub(r"<think(?:ing)?>.*$", "", text, flags=re.DOTALL)
    stripped = text.strip()

    # Remove leading "thinking:..." preamble
    stripped = re.sub(r"(?is)^thinking:.*?(?=\n\s*\n)", "", stripped).strip()

    # Drop numbered analysis lines (e.g. "1. Analyze...", "2. Check...")
    # and keep only the prose that follows them
    if re.match(r"^\d+\.\s", stripped):
        lines = stripped.split("\n")
        last_step = -1
        for i, line in enumerate(lines):
            if re.match(r"^\d+\.\s", line.strip()):
                last_step = i
        if last_step >= 0 and last_step < len(lines) - 1:
            remainder = "\n".join(lines[last_step + 1:]).strip()
            if remainder:
                stripped = remainder

    # Strip trailing meta-commentary sentences ("I'll craft a response...", etc.)
    _META = re.compile(
        r"^(i'?ll |i will |i should |i'm going to |i need to |now i'?ll |let me |"
        r"i can now |i'll craft|i will craft|i'll provide|i will provide)",
        re.IGNORECASE
    )
    sentences = re.split(r'(?<=[.!?])\s+', stripped)
    sentences = [s for s in sentences if s.strip() and not _META.match(s.strip())]
    stripped = " ".join(sentences).strip()

    # Strip "Let me / Looking at / I can see" narration lines from the start
    _NARRATION = re.compile(
        r'^(let me|looking at|i can see|i\'ll|let\'s|i will now|'
        r'to answer (this|your)|based on the (wiki|page)|'
        r'the page (says|mentions|shows|indicates)|'
        r'from the (wiki|page)|checking the|reading the)[^\n]*\n*',
        re.IGNORECASE
    )
    lines = stripped.split("\n")
    while lines and _NARRATION.match(lines[0]):
        lines = lines[1:]
    stripped = "\n".join(lines).strip()

    # Frontend is plain-text only — strip all asterisks and leading "- " bullet markers
    stripped = re.sub(r"\*+", "", stripped).strip()
    stripped = re.sub(r"(?m)^- ", "", stripped).strip()

    return stripped


async def zai_complete(prompt: str,
                        system: str = "You are a helpful assistant.",
                        max_tokens: int = 500,
                        temperature: float = 0.3,
                        model: str = None,
                        strip: bool = True) -> str:
    m = model or os.getenv("ZAI_MODEL", "glm-5.1")
    resp = await _client().chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
        temperature=temperature
    )
    raw = resp.choices[0].message.content
    return _strip_thinking(raw) if strip else raw


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
