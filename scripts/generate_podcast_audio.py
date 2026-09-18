#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.openai.com/v1/audio/speech"
MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
VOICE = os.getenv("OPENAI_TTS_VOICE", "cedar")
MAX_CHARS = 3800
VOICE_INSTRUCTIONS = (
    "Read this as a calm, concise executive news briefing for rural healthcare leaders. "
    "Use a measured, professional American English delivery, natural pauses, and clear emphasis "
    "on dates, deadlines, financial figures, and action items. Avoid theatrical delivery. "
    "Target roughly 145 to 155 words per minute."
)

def spoken_body(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("episode title:"):
        for i, line in enumerate(lines):
            if i > 0 and not line.strip():
                return "\n".join(lines[i + 1:]).strip()
    return text.strip()

def split_long_piece(piece: str):
    piece = piece.strip()
    if len(piece) <= MAX_CHARS:
        return [piece]
    sentences = re.split(r'(?<=[.!?])\s+', piece)
    chunks, current = [], ""
    for sentence in sentences:
        if len(sentence) > MAX_CHARS:
            words = sentence.split()
            buf = ""
            for word in words:
                candidate = (buf + " " + word).strip()
                if len(candidate) > MAX_CHARS and buf:
                    chunks.append(buf)
                    buf = word
                else:
                    buf = candidate
            if buf:
                if current and len(current) + 1 + len(buf) <= MAX_CHARS:
                    current = current + " " + buf
                else:
                    if current:
                        chunks.append(current)
                    current = buf
            continue
        candidate = (current + " " + sentence).strip()
        if len(candidate) > MAX_CHARS and current:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks

def chunk_text(text: str):
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chunks, current = [], ""
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(split_long_piece(paragraph))
            continue
        candidate = (current + "\n\n" + paragraph).strip()
        if len(candidate) > MAX_CHARS and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks

def synthesize(api_key: str, text: str, output: Path):
    payload = {
        "model": MODEL,
        "voice": VOICE,
        "input": text,
        "instructions": VOICE_INSTRUCTIONS,
        "response_format": "mp3",
        "speed": 1.0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                output.write_bytes(response.read())
            return
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 3)
    raise RuntimeError(f"TTS request failed after 3 attempts: {last_error}")

def main():
    if len(sys.argv) != 3:
        print("Usage: generate_podcast_audio.py <script.txt> <output.mp3>", file=sys.stderr)
        return 2

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set. Audio generation skipped.", file=sys.stderr)
        return 3

    script_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    body = spoken_body(script_path.read_text(encoding="utf-8"))
    if not body:
        raise RuntimeError("Podcast script contains no spoken body.")

    chunks = chunk_text(body)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            part = temp / f"part-{i:02d}.mp3"
            print(f"Synthesizing part {i}/{len(chunks)} ({len(chunk)} chars)")
            synthesize(api_key, chunk, part)
            parts.append(part)

        concat_file = temp / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in parts),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c", "copy", str(output_path),
            ],
            check=True,
        )

    print(f"Wrote {output_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
