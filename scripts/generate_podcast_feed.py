#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = "https://6nywfpnnw8-wq.github.io/The-Rural-Update"
FEED_URL = f"{BASE_URL}/podcast.xml"
ART_URL = f"{BASE_URL}/podcast-art.png"
SITE_URL = f"{BASE_URL}/"
TZ = ZoneInfo("America/Chicago")

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ATOM = "http://www.w3.org/2005/Atom"\nPODCAST = "https://podcastindex.org/namespace/1.0"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("content", CONTENT)
ET.register_namespace("atom", ATOM)\nET.register_namespace("podcast", PODCAST)

def q(ns, tag):
    return f"{{{ns}}}{tag}"

def parse_script(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    meta = {}
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            body_start = i + 1
            break
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    body = "\n".join(lines[body_start:]).strip()
    intro = ""
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if p and not p.isupper():
            intro = p
            break
    return meta, body, intro

def duration_seconds(audio_path: Path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)
    ], text=True).strip()
    return max(0, int(round(float(out))))

def duration_text(seconds: int):
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def add_text(parent, tag, text, ns=None):
    el = ET.SubElement(parent, q(ns, tag) if ns else tag)
    el.text = text
    return el

def main():
    root_dir = Path(".")
    audio_dir = root_dir / "audio"
    script_dir = root_dir / "podcast-script"
    episodes = []

    for audio_path in sorted(audio_dir.glob("*.mp3"), reverse=True):
        date = audio_path.stem
        script_path = script_dir / f"{date}.txt"
        if not script_path.exists():
            continue
        meta, body, intro = parse_script(script_path)
        title = meta.get("episode title", f"The Rural Update | {date}")
        try:
            pub_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=6, minute=0, tzinfo=TZ)
        except ValueError:
            continue
        dur = duration_seconds(audio_path)
        episodes.append({
            "date": date,
            "title": title,
            "description": intro or "Daily rural healthcare executive intelligence briefing.",
            "pub_dt": pub_dt,
            "audio_path": audio_path,
            "audio_url": f"{BASE_URL}/audio/{date}.mp3",
            "length": audio_path.stat().st_size,
            "duration": duration_text(dur),
        })

    if not episodes:
        print("No complete podcast episodes found.", file=sys.stderr)
        return 1

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", "The Rural Update")
    add_text(channel, "link", SITE_URL)
    add_text(channel, "description", "A concise daily executive briefing on rural healthcare policy, operations, finance, Oklahoma developments, federal policy, and emerging technology.")
    add_text(channel, "language", "en-us")
    add_text(channel, "copyright", "The Rural Update")
    add_text(channel, "lastBuildDate", format_datetime(datetime.now(TZ)))
    ET.SubElement(channel, q(ATOM, "link"), {"href": FEED_URL, "rel": "self", "type": "application/rss+xml"})
    add_text(channel, "author", "The Rural Update", ITUNES)
    add_text(channel, "summary", "Daily rural healthcare executive intelligence in under 15 minutes.", ITUNES)
    add_text(channel, "explicit", "false", ITUNES)
    add_text(channel, "type", "episodic", ITUNES)
    add_text(channel, "block", "Yes", ITUNES)
    ET.SubElement(channel, q(ITUNES, "image"), {"href": ART_URL})
    category = ET.SubElement(channel, q(ITUNES, "category"), {"text": "Health & Fitness"})
    ET.SubElement(category, q(ITUNES, "category"), {"text": "Medicine"})

    image = ET.SubElement(channel, "image")
    add_text(image, "url", ART_URL)
    add_text(image, "title", "The Rural Update")
    add_text(image, "link", SITE_URL)

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        add_text(item, "title", ep["title"])
        add_text(item, "description", ep["description"])
        add_text(item, "encoded", ep["description"], CONTENT)
        add_text(item, "pubDate", format_datetime(ep["pub_dt"]))
        guid = add_text(item, "guid", f"the-rural-update-{ep['date']}")
        guid.set("isPermaLink", "false")
        ET.SubElement(item, "enclosure", {
            "url": ep["audio_url"],
            "length": str(ep["length"]),
            "type": "audio/mpeg",
        })
        add_text(item, "duration", ep["duration"], ITUNES)
        add_text(item, "episodeType", "full", ITUNES)
        add_text(item, "explicit", "false", ITUNES)
        add_text(item, "summary", ep["description"], ITUNES)\n        ET.SubElement(item, q(PODCAST, "transcript"), {"url": ep["transcript_url"], "type": "text/html"})

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write("podcast.xml", encoding="utf-8", xml_declaration=True)
    print(f"Wrote podcast.xml with {len(episodes)} episode(s).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
