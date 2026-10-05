### app.py file 

from backend import add_order,edit_order,remove_order,get_table_orders,add_table_note,is_table_available

import os
import time
import numpy as np
import sounddevice as sd

from scipy.io.wavfile import write
from dotenv import load_dotenv
from groq import Groq

from langchain_groq import ChatGroq
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(
    api_key=GROQ_API_KEY
)



# LLM


llm = ChatGroq(
    model="openai/gpt-oss-120b"
)

# AUDIO SETTINGS


INPUT_DEVICE_INDEX = 2
OUTPUT_DEVICE_INDEX = 5

try:
    _info = sd.query_devices(INPUT_DEVICE_INDEX, "input")
    CHANNELS = min(2, _info["max_input_channels"])
    SAMPLE_RATE = int(_info["default_samplerate"])
except Exception:
    CHANNELS, SAMPLE_RATE = 1, 16000

CHUNK_DURATION = 0.3
SILENCE_THRESHOLD = 0.02
INITIAL_WAIT = 4
SILENCE_DURATION = 5
GREETING = "Hello sir, how can I help you related to your order? First, what is your table number?"



# ADD ORDER TOOL


@tool
def add_order_tool(table_number: int,item: str,quantity: int):
    """Add a new item to a restaurant table order."""

    return add_order(table_number,item,quantity)

@tool
def edit_order_tool(table_number: int,item: str,quantity: int):
    """Edit the quantity of an existing item in a table order."""
    return edit_order(table_number,item,quantity)


@tool
def remove_order_tool(table_number: int,item: str):
    """Remove an item from a restaurant table order."""

    return remove_order(table_number,item)



@tool
def get_table_order_tool(table_number: int):
    """Get the current order of a restaurant table."""

    return get_table_orders(table_number)


@tool
def add_table_note_tool(table_number: int, note: str):
    """Add a note to a table."""
    return add_table_note(table_number=table_number, note=note)

@tool
def get_table_status_tool(table_number: int):
    """Check the status of a table: available, occupied, reserved or cleaning."""
    return is_table_available(table_number)


# agent

checkpointer = InMemorySaver()
agent = create_agent(

    model=llm,

    tools=[
        add_order_tool,
        edit_order_tool,
        remove_order_tool,
        get_table_order_tool,
        add_table_note,
        get_table_status_tool
    ],
    checkpointer=checkpointer,

    system_prompt="""
You are a restaurant order management agent.

Your job is to manage restaurant table orders using the available tools.

1. Order-Related Queries Only
Handle only queries related to restaurant orders, such as:
Adding an item
Editing an item
Removing an item
Checking an order
Order status
Table/order-related requests
If the user asks something unrelated to an order, reply:
"Please ask a query related to the order."
2. Understand the User's Intent
Understand the user's request even if it is not perfectly worded.
If the user mentions useful information related to the order but it does not fit directly into an order item, add it as a note if the available tool supports notes.
Do not invent information that the user did not provide.
3. Table Availability Rule
When the user provides a table number for the first time, check whether that table is available before taking the order.
If the table is available, proceed with the order.
Once a table has been verified and the order process has started, remember that table for the current conversation.
Do not repeatedly check the same table's availability for every order operation.
4. If the Table Is Not Available
Do not take or modify the order for that table.
Ask the user to provide another available table number.
Alternatively, tell the user to contact restaurant reception.
Do not automatically check other tables unless the user provides a new table number.
5. Existing Order
If a table already has an order, do not create a duplicate order.
Edit the existing order when the user wants to change quantity or item.
Remove an item when the user asks to remove it.
Check the existing order when the user asks what they ordered.
6. Response Length
Keep every response short, clear, and meaningful.
Do not give long explanations.
Do not repeat the user's complete order unnecessarily.
Confirm only the important action.

8. Every user message starts with "[Caller mobile: <number>]".
   It only identifies the caller. Do not use it in tools and
   do not read it out loud.
9. At the start of the call you asked the caller for their table number.
   Their first reply is that table number. If they say it in words,
   convert it to digits.
Examples:

"Added 2 pizzas to table 5."
"Removed the burger from table 5."
"Table 5 is unavailable. Please provide another table number."
"Please ask a query related to the order."
7. Important Behavior
Never invent a table number, order item, quantity, or availability status.
Use the available tools whenever an order operation is required.
Follow the tool result exactly.
Keep responses concise while still providing the required information.
"""
)



# RECORD VOICE

def record_voice():

    print("\n Recording started...")
    print(f" speek (channels={CHANNELS}, rate={SAMPLE_RATE})")

    audio_chunks = []
    recording_start = time.time()
    silence_start = None
    chunk_frames = int(SAMPLE_RATE * CHUNK_DURATION)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        device=INPUT_DEVICE_INDEX
    ) as stream:

        while True:

            audio, _ = stream.read(chunk_frames)

            # stereo -> mono
            audio = audio.mean(axis=1, keepdims=True)

            audio_chunks.append(audio)

            volume = np.sqrt(np.mean(audio ** 2))
            elapsed_time = time.time() - recording_start

            # Pehle 10 sec silence check nahi
            if elapsed_time < INITIAL_WAIT:
                print(f"\r {elapsed_time:.1f}s | Volume: {volume:.4f} | recording", end="")
                continue

            if volume < SILENCE_THRESHOLD:

                if silence_start is None:
                    silence_start = time.time()

                silence_time = time.time() - silence_start

                print(
                    f"\r{elapsed_time:.1f}s | Volume: {volume:.4f} | "
                    f"silence {silence_time:.1f}/{SILENCE_DURATION}s",
                    end=""
                )

                if silence_time >= SILENCE_DURATION:
                    print("\n\n Silence detected.")
                    print(" Recording stopped.")
                    break

            else:
                silence_start = None
                print(f"\r {elapsed_time:.1f}s | Volume: {volume:.4f} |  speech", end="")

    audio_data = np.concatenate(audio_chunks, axis=0)
    audio_data = np.int16(audio_data * 32767)

    
    write("voice.wav", SAMPLE_RATE, audio_data)
    print(" Audio saved: voice.wav")

    return "voice.wav"


# SPEECH TO TEXT


def speech_to_text(audio_file):

    print(
        "\n Converting speech to text..."
    )

    with open(
        audio_file,
        "rb"
    ) as file:

        transcription = client.audio.transcriptions.create(

            file=(
                "voice.wav",
                file.read()
            ),

            model="whisper-large-v3-turbo",

            response_format="text"
        )

    return str(getattr(transcription, "text", transcription)).strip()


def run_agent(history):

    print("\n🤖 Agent is thinking...")

    response = agent.invoke({"messages": history})

    return response["messages"][-1].content, response["messages"]


def run_agent_for_caller(phone, user_text):
    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"[Caller mobile: {phone}] {user_text}"}]},
        config={"configurable": {"thread_id": phone}},
    )

    table = None
    for m in result["messages"]:
        for call in getattr(m, "tool_calls", None) or []:
            if call["args"].get("table_number"):
                table = call["args"]["table_number"]

    return result["messages"][-1].content, table

def reset_caller_memory(phone):
    checkpointer.delete_thread(phone)

# TEXT TO SPEECH


def text_to_speech(text):

    import pyttsx3

    print(
        "\n Agent is speaking..."
    )

    engine = pyttsx3.init()

    engine.setProperty(
        "rate",
        170
    )

    engine.say(text)

    engine.runAndWait()



# VOICE ASSISTANT

def voice_assistant():

    chat_history = [{"role": "assistant", "content": GREETING}]
    first_time = True

    while True:

        print("\n" + "=" * 50)
        print("Press Y + Enter → 🎤 Speak")
        print("Press R + Enter → 🔄 Reset memory")
        print("Press Q + Enter → ❌ Exit")
        print("=" * 50)

        command = input(">>> ").strip().lower()

        if command == "q":
            print("\n👋 Voice Agent stopped.")
            break

        if command == "r":
            chat_history = [{"role": "assistant", "content": GREETING}]
            first_time = True
            print("🔄 Memory reset.")
            continue

        if command == "y":

            if first_time:
                text_to_speech(GREETING)
                first_time = False

            audio_file = record_voice()
            user_text = speech_to_text(audio_file)

            print("\n You:")
            print(user_text)

            if not user_text.strip():
                print("⚠️ No speech detected.")
                continue

            agent_response, _ = run_agent_for_caller("laptop", user_text)

            print("\n Agent:")
            print(agent_response)

            text_to_speech(agent_response)

        else:
            print("⚠️ Please press Y, R or Q.")

# START PROGRAM


if __name__ == "__main__":

    voice_assistant()