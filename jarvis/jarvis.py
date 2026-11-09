"""
JARVIS — a Gemini-powered personal assistant that can pull and read GitHub repos.

    python jarvis.py            # type to Jarvis
    python jarvis.py --voice    # talk to Jarvis (needs the optional voice packages)

Needs GEMINI_API_KEY (free at https://aistudio.google.com/apikey), set in the
environment or in a .env file next to this script.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv(HERE / ".env")

from google import genai                      # noqa: E402
from google.genai import types                # noqa: E402

import github_tools                           # noqa: E402

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = """You are JARVIS, a personal AI assistant in the style of Tony Stark's JARVIS:
professional, efficient, calm and slightly witty. Address the user as "sir" unless
they ask otherwise. Keep spoken-style answers short; go into detail only when asked.

You can work with the user's GitHub repositories using your tools:
- "my repos" -> list_repos
- "pull / get / download / update <repo>" -> pull_repo (it clones if missing)
- "update all my repos" -> pull_all_repos
- To answer questions about a repo's code, pull it if needed, then use
  list_files and read_file to look at the actual code before answering.
Never invent tool results. If a tool reports an error, explain it plainly.
The current date and time is {now}."""


# ── Voice (optional) ─────────────────────────────────────────────────────────

class Voice:
    def __init__(self):
        try:
            import pyttsx3
            import speech_recognition as sr
        except ImportError:
            sys.exit("Voice mode needs: pip install -r requirements-voice.txt")
        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.tts = pyttsx3.init()

    def listen(self) -> str:
        with self.sr.Microphone() as mic:
            self.recognizer.adjust_for_ambient_noise(mic, duration=0.4)
            print("🎙️  Listening...")
            audio = self.recognizer.listen(mic, phrase_time_limit=15)
        try:
            return self.recognizer.recognize_google(audio)
        except self.sr.UnknownValueError:
            return ""

    def say(self, text: str) -> None:
        # Don't read code blocks or long listings aloud.
        spoken = text.split("```")[0].strip()
        if len(spoken) > 600:
            spoken = spoken[:600].rsplit(".", 1)[0] + ". The rest is on screen, sir."
        self.tts.say(spoken)
        self.tts.runAndWait()


# ── Main loop ────────────────────────────────────────────────────────────────

def make_chat():
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        sys.exit(
            "GEMINI_API_KEY is not set.\n"
            "Get a free key at https://aistudio.google.com/apikey and put it in "
            f"{HERE / '.env'} as:  GEMINI_API_KEY=your-key"
        )
    client = genai.Client()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(now=datetime.now().strftime("%A %d %B %Y, %H:%M")),
        tools=github_tools.TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=15),
    )
    return client.chats.create(model=MODEL, config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS — Gemini personal assistant")
    parser.add_argument("--voice", action="store_true", help="talk instead of type")
    args = parser.parse_args()

    chat  = make_chat()
    voice = Voice() if args.voice else None

    greeting = "JARVIS online. How can I help, sir?"
    print(f"\n🤖 {greeting}\n   (type 'exit' to quit)\n")
    if voice:
        voice.say(greeting)

    while True:
        try:
            user = voice.listen() if voice else input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        user = user.strip()
        if not user:
            continue
        if voice:
            print(f"You: {user}")
        if user.lower() in {"exit", "quit", "bye", "goodbye", "shut down"}:
            break

        try:
            reply = chat.send_message(user).text or "Done, sir."
        except Exception as e:
            reply = f"I ran into a problem talking to Gemini: {e}"
        print(f"\n🤖 JARVIS: {reply}\n")
        if voice:
            voice.say(reply)

    bye = "Goodbye, sir."
    print(f"🤖 {bye}")
    if voice:
        voice.say(bye)


if __name__ == "__main__":
    main()
