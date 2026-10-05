# Restaurant Voice Agent

A voice agent that takes restaurant table orders over a phone call. The caller speaks, the agent updates the table's order through backend functions, and replies in speech. A separate Streamlit app lets the restaurant staff see and manage the same tables.

Built by Jeet Kumar Gupta.

## What it does

- Caller dials an Exotel number, the agent greets them and asks for the table number.
- Caller can add, edit or remove items, check the current order, or leave a note for the table.
- Staff manage tables, orders, status and notes from a Streamlit dashboard.
- Each caller gets their own conversation memory, keyed by their mobile number. When a table goes from occupied back to available, that caller's memory is cleared and the next call starts a fresh session.
- The same agent also runs in a laptop mode (mic and speaker), which is handy for testing without a phone.

## How it works

```
Phone call -> Exotel Voicebot -> WebSocket (ngrok) -> server.py
                                                       |
                         silence detection -> Whisper (Groq) speech to text
                                                       |
                         LangChain agent (gpt-oss-120b on Groq) + tools
                                                       |
                                  backend.py <-> order.json
                                                       |
                         edge-tts -> 8 kHz PCM -> back to the caller
```

The listening rule per turn: the agent ignores silence for the first 5 seconds, then stops recording after 3 seconds of continuous silence and runs. The same 5 + 3 rule repeats after every agent reply. Both values are `START_WAIT` and `SILENCE_STOP` at the top of `server.py`.

## Project files

| File | Purpose |
|---|---|
| `backend.py` | Table and order logic, stored in `order.json`. Every function returns `{success, message, data}`. |
| `app.py` | The agent: tools, system prompt, Groq speech to text, memory (`InMemorySaver`). Also has the laptop mic/speaker mode. |
| `server.py` | FastAPI WebSocket server that Exotel connects to. Handles audio, silence detection, TTS and per-caller sessions. |
| `ui.py` | Streamlit staff dashboard (floor view, manage table, search item, setup). |
| `order.json` | Table data. Created automatically if missing. |
| `.env` | Holds `GROQ_API_KEY`. |

## Requirements

- Python 3.10+
- ffmpeg and ffprobe on the machine (pydub needs them to convert TTS audio)
- A Groq API key
- For phone calls: an Exotel account with a number, and ngrok (or any public HTTPS host)

Install the Python packages:

```
pip install -r requirements.txt
```

If you set it up by hand, the main ones are: `langchain`, `langchain-groq`, `langgraph`, `groq`, `python-dotenv`, `fastapi`, `uvicorn`, `edge-tts`, `pydub`, `numpy`, `scipy`, `sounddevice`, `pyttsx3`, `streamlit`.

## Setup

**1. Environment file**

Create `.env` next to the code with one line, no quotes and no spaces around `=`:

```
GROQ_API_KEY=your_key_here
```

Save it as plain UTF-8. A BOM or extra text on the first line gives the `python-dotenv could not parse` warning.

**2. Table data**

`order.json` looks like this. Statuses can be `available`, `occupied`, `reserved` or `cleaning`.

```json
{
    "tables": {
        "1": { "status": "occupied", "orders": [{ "item": "Paneer Tikka", "quantity": 2 }], "notes": "Less spicy" },
        "2": { "status": "available", "orders": [], "notes": "" }
    }
}
```

You can also create tables from the Setup page in the dashboard.

**3. ffmpeg path (Windows)**

If ffmpeg is not on your PATH, add its `bin` folder at the top of `server.py`, before the pydub import:

```python
import os
os.environ["PATH"] += os.pathsep + r"C:\path\to\ffmpeg\bin"
```

## Running

**Staff dashboard**

```
streamlit run ui.py
```

**Laptop voice mode** (no phone needed)

Set `INPUT_DEVICE_INDEX` in `app.py` to your mic (`sd.query_devices()` lists them), then:

```
python app.py
```

**Phone agent**

1. Start the server:
   ```
   uvicorn server:app --port 8000
   ```
2. In a second terminal, expose it:
   ```
   ngrok http 8000
   ```
3. In the Exotel dashboard, open the flow linked to your number, add a **Voicebot** applet and set its URL to `wss://<your-ngrok-domain>/ws`. Bidirectional mode is needed so the agent can speak back. Save the flow.
4. Call your Exotel number from a registered mobile.

Free ngrok URLs change on every restart, so update the Voicebot URL in Exotel each time.

## Agent tools

| Tool | Does |
|---|---|
| `get_table_status_tool` | Checks if a table is available |
| `add_order_tool` | Adds an item (starts a session on an available table) |
| `edit_order_tool` | Changes the quantity of an item already ordered |
| `remove_order_tool` | Removes an item. The last item removed frees the table |
| `get_table_order_tool` | Reads the current order |
| `add_table_note_tool` | Saves a note on the table |

The agent only handles order-related requests and replies with a short answer, since the reply is turned into speech.

## Known limits

- Memory is `InMemorySaver`, so it is lost when the server restarts. The order itself stays in `order.json`. Switching to a SQLite checkpointer would make memory persistent.
- `order.json` is a single file with no locking, which is fine for a demo and one server, not for heavy parallel use.
- Phone audio is 8 kHz, so Whisper sometimes mis-spells dish names. Adding the menu items to the speech-to-text prompt helps.
- Exotel trial accounts only accept calls from verified numbers.
- The Voicebot message format and sample rate can change with Exotel versions, so check their Voicebot docs if the greeting does not play.

## Tech stack

Groq (Whisper large-v3-turbo, gpt-oss-120b), LangChain and LangGraph, FastAPI, edge-tts, pydub with ffmpeg, Exotel Voicebot, ngrok, Streamlit.