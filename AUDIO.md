# Podcast audio generation

The Rural Update can generate an MP3 from each dated script in `podcast-script/`.

## One-time setup

Add a repository Actions secret named `OPENAI_API_KEY`:

1. Open the repository on GitHub.
2. Go to **Settings > Secrets and variables > Actions**.
3. Choose **New repository secret**.
4. Name it `OPENAI_API_KEY`.
5. Paste an OpenAI API key with billing enabled.

The workflow intentionally skips audio generation, without failing the publication pipeline, when the secret is absent.

## Daily output

When a new file such as `podcast-script/2026-09-19.txt` is committed to `main`, the workflow:

1. Selects the latest dated podcast script.
2. Splits long scripts into API-safe chunks.
3. Generates speech with `gpt-4o-mini-tts` using the `cedar` voice.
4. Concatenates the chunks into `audio/YYYY-MM-DD.mp3`.
5. Commits the MP3 to `main`.
6. Triggers the Pages deployment workflow so the audio file is publicly reachable from the site.

The default narration instruction calls for a calm, concise executive-news delivery at roughly 145 to 155 words per minute.

## Current scope

This phase generates and publishes MP3 files only. RSS feed generation and Apple Podcasts subscription are intentionally deferred to the next phase.
