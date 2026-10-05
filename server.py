import base64
import json
import wave
import numpy as np
import edge_tts
from io import BytesIO
import os
import time
import asyncio

START_WAIT = 2      # listening shuru hone ke baad itne sec silence check nahi
SILENCE_STOP = 2     # uske baad itni lagatar chup = recording stop, agent chalega

FFMPEG_BIN = r"C:\Users\gupje\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin"
os.environ["PATH"] += os.pathsep + FFMPEG_BIN
from pydub import AudioSegment
FFMPEG_BIN = r"C:\Users\gupje\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin"

AudioSegment.converter = FFMPEG_BIN + r"\ffmpeg.exe"
AudioSegment.ffmpeg = FFMPEG_BIN + r"\ffmpeg.exe"
AudioSegment.ffprobe = FFMPEG_BIN + r"\ffprobe.exe"
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# app.py ka agent aur speech_to_text reuse
from app import agent, speech_to_text, GREETING, run_agent_for_caller, reset_caller_memory
from backend import check_table_status

app = FastAPI()

RATE = 8000                 # Exotel ka default (docs mein check kar lena)
SILENCE_LEVEL = 0.01
SILENCE_SECONDS = 1.0       # itni chup ke baad utterance khatam maano


async def tts_pcm(text):
    """Text -> 8kHz mono 16-bit raw PCM bytes."""
    comm = edge_tts.Communicate(text, "en-IN-NeerjaNeural")
    mp3 = b""
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    seg = AudioSegment.from_file(BytesIO(mp3), format="mp3")
    seg = seg.set_frame_rate(RATE).set_channels(1).set_sample_width(2)
    return seg.raw_data


async def send_audio(ws, stream_sid, pcm):
    # chhote tukdon mein bhejo (320 bytes ke multiple)
    step = 3200
    for i in range(0, len(pcm), step):
        await ws.send_text(json.dumps({
            "event": "media",
            "stream_sid": stream_sid,
            "media": {"payload": base64.b64encode(pcm[i:i + step]).decode()},
        }))


def save_wav(pcm, path="call.wav"):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return path


async def speak(ws, stream_sid, text):
    """Bolo, aur kitne second ka audio gaya wo wapas do."""
    pcm = await tts_pcm(text)
    await send_audio(ws, stream_sid, pcm)
    return len(pcm) / (RATE * 2)   # 16-bit mono


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    stream_sid = None
    caller = None
    call_sid = None
    had_table = False

    buffer = b""
    listen_time = 0.0
    quiet_time = 0.0
    heard_speech = False
    ignore_until = 0.0

    def reset_listen():
        nonlocal buffer, listen_time, quiet_time, heard_speech
        buffer, listen_time, quiet_time, heard_speech = b"", 0.0, 0.0, False

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            event = msg.get("event")

            if event == "start":
                start = msg.get("start", {})
                stream_sid = msg.get("stream_sid") or start.get("stream_sid")
                call_sid = start.get("call_sid")
                caller = start.get("from") or call_sid
                print(f"📞 Call from {caller} | call_sid={call_sid}")

                dur = await speak(ws, stream_sid, GREETING)
                ignore_until = time.time() + dur
                reset_listen()

            elif event == "media":
                if time.time() < ignore_until:
                    continue

                pcm = base64.b64decode(msg["media"]["payload"])
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
                if len(samples) == 0:
                    continue

                volume = float(np.sqrt(np.mean(samples ** 2)))
                chunk_sec = len(samples) / RATE

                buffer += pcm
                listen_time += chunk_sec

                if volume >= SILENCE_LEVEL:
                    heard_speech = True
                    quiet_time = 0.0
                elif listen_time >= START_WAIT:
                    quiet_time += chunk_sec
                else:
                    quiet_time = 0.0

                if listen_time >= START_WAIT and quiet_time >= SILENCE_STOP:
                    audio, spoke = buffer, heard_speech
                    reset_listen()

                    if not spoke:
                        continue

                    wav = save_wav(audio, f"call_{call_sid}.wav")
                    text = await asyncio.to_thread(speech_to_text, wav)
                    print("Caller:", text)
                    if not text:
                        continue

                    reply, table = await asyncio.to_thread(run_agent_for_caller, caller, text)
                    print("Agent:", reply)

                    if table:
                        info = check_table_status(table).get("data") or {}
                        status = info.get("status")

                        if status == "occupied":
                            had_table = True
                        elif status == "available" and had_table:
                            reset_caller_memory(caller)
                            had_table = False
                            print(f"🔄 New session for {caller}")

                    dur = await speak(ws, stream_sid, reply)
                    ignore_until = time.time() + dur
                    reset_listen()

            elif event == "stop":
                break

    except WebSocketDisconnect:
        pass