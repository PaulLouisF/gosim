"""Speechmatics TTS — preview API. Returns empty bytes on any error so the app
remains fully functional when the key is absent or the endpoint is unavailable.

Available voices: sarah (UK female), theo (UK male), megan (US female), jack (US male)

Set TTS_ENABLED=false in .env to skip TTS entirely (useful for latency testing).
"""
import os
import httpx

_DEFAULT_VOICE = "megan"  # US female


async def speak(text: str, voice: str = _DEFAULT_VOICE) -> bytes:
    """Convert text to speech. Returns MP3 bytes, or b'' on failure."""
    if os.getenv("TTS_ENABLED", "true").lower() == "false":
        return b""

    api_key = os.getenv("SPEECHMATICS_API_KEY", "")
    if not api_key or api_key == "your_key_here":
        return b""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://preview.tts.speechmatics.com/generate/{voice}",
                json={"text": text},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15.0
            )
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        print(f"[TTS] skipped — {e}")
        return b""

