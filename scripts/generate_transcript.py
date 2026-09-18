#!/usr/bin/env python3
import html
import re
import sys
from pathlib import Path

SITE_TITLE = "The Rural Update"

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
    return meta, body

def is_heading(paragraph: str):
    stripped = paragraph.strip()
    if not stripped:
        return False
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    return bool(letters) and stripped == stripped.upper() and len(stripped) <= 100

def render_html(meta, body, date):
    title = meta.get("episode title", f"{SITE_TITLE} | {date}")
    generated = meta.get("generated time ct", "")
    runtime = meta.get("estimated run time", "")
    parts = []
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if not p:
            continue
        escaped = html.escape(p)
        if is_heading(p):
            parts.append(f"<h2>{escaped.title()}</h2>")
        else:
            parts.append(f"<p>{escaped.replace(chr(10), '<br>')}</p>")
    body_html = "\n".join(parts)
    meta_bits = [f"Edition date: {html.escape(date)}"]
    if generated:
        meta_bits.append(f"Generated: {html.escape(generated)}")
    if runtime:
        meta_bits.append(f"Estimated run time: {html.escape(runtime)}")
    meta_line = " · ".join(meta_bits)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} Transcript</title>
<style>
:root{{--navy:#0f2942;--gold:#c8963e;--gray:#65707f;--bg:#f3f5f7;--card:#fff;--border:#e0e5ea}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:#20262e;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.65}}
.wrap{{max-width:760px;margin:auto;padding:20px 16px 60px}}
header{{background:var(--navy);color:#fff;border-radius:14px;padding:22px}}
header h1{{margin:0 0 8px;font-size:24px}}
header p{{margin:0;color:#c7d6e5;font-size:13px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:22px;margin-top:16px}}
h2{{color:var(--navy);font-size:15px;letter-spacing:.04em;margin:26px 0 8px;text-transform:uppercase}}
h2:first-child{{margin-top:0}}
p{{font-size:15px;margin:0 0 16px}}
a{{color:var(--navy);font-weight:700;text-decoration:none}}
.back{{display:inline-block;margin-top:18px}}
footer{{color:var(--gray);font-size:12px;text-align:center;margin-top:22px}}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>{html.escape(title)}</h1>
<p>{meta_line}</p>
</header>
<main class="card">
{body_html}
<a class="back" href="../">Back to The Rural Update</a>
</main>
<footer>Podcast transcript · {SITE_TITLE}</footer>
</div>
</body>
</html>
"""

def main():
    if len(sys.argv) != 3:
        print("Usage: generate_transcript.py <script.txt> <output.html>", file=sys.stderr)
        return 2
    script = Path(sys.argv[1])
    out = Path(sys.argv[2])
    meta, body = parse_script(script)
    date = script.stem
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(meta, body, date), encoding="utf-8")
    print(f"Wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
