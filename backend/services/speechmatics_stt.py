"""Speechmatics Real-Time STT via WebSocket."""
import asyncio
import json
import os
import websockets

SPEECHMATICS_WS = "wss://eu2.rt.speechmatics.com/v2"


async def transcribe_stream(audio_generator, language: str = "en") -> str:
    api_key = os.getenv("SPEECHMATICS_API_KEY")
    config = {
        "message": "StartRecognition",
        "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
        "transcription_config": {"language": language, "enable_partials": True, "max_delay": 2.0}
    }
    parts = []
    async with websockets.connect(
        SPEECHMATICS_WS,
        extra_headers={"Authorization": f"Bearer {api_key}"}
    ) as ws:
        await ws.send(json.dumps(config))

        async def send():
            async for chunk in audio_generator:
                await ws.send(chunk)
            await ws.send(json.dumps({"message": "EndOfStream", "last_seq_no": 0}))

        async def recv():
            async for msg in ws:
                d = json.loads(msg)
                if d.get("message") == "AddTranscript":
                    parts.append(d["metadata"]["transcript"])
                elif d.get("message") == "EndOfTranscript":
                    break

        await asyncio.gather(send(), recv())
    return "".join(parts).strip()
