"""Speechmatics TTS — key moments only. Returns empty bytes on any error so the app
remains fully functional when the key is absent or the endpoint is unavailable."""
import os
import httpx


async def speak(text: str, voice: str = "en-US-Neural") -> bytes:
    """Convert text to speech. Returns MP3 bytes, or b'' on failure."""
    api_key = os.getenv("SPEECHMATICS_API_KEY", "")
    if not api_key or api_key == "your_key_here":
        return b""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://mp.speechmatics.com/v1/tts",
                json={
                    "input": {"text": text},
                    "voice": {"name": voice, "language": "en"},
                    "output_format": {"type": "mp3", "sample_rate": 22050}
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15.0
            )
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        print(f"[TTS] skipped — {e}")
        return b""
