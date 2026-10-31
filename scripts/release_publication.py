"""Versioned delivery requirements. Editions from October 31 are app updates."""
from datetime import date

APP_ONLY_FROM = '2026-10-31'


def app_only(edition_date):
    return date.fromisoformat(edition_date) >= date.fromisoformat(APP_ONLY_FROM)


def app_required_paths(edition_date):
    date.fromisoformat(edition_date)
    return {'index.html', 'archive/catalog.json', f'archive/{edition_date}.html',
            'data/intelligence.json', 'data/signals.json', 'web/release-runtime.js',
            'web/release.css', 'sw.js', 'manifest.webmanifest'}


def complete_app_manifest(manifest, edition_date):
    """Metadata check only. Public delivery still requires every artifact's hash."""
    files = manifest.get('files', {})
    return (app_only(edition_date) and manifest.get('schema_version') == 1
            and manifest.get('edition_date') == edition_date
            and manifest.get('publication_mode') == 'app'
            and 'audio_status' not in manifest and isinstance(files, dict)
            and app_required_paths(edition_date).issubset(files)
            and not any(p in {'podcast.xml','podcast-art.png'} or p.endswith(('.mp3','.wav'))
                        or p.startswith(('audio/', 'transcript/',
                        'podcast-script/', 'data/audio-quality-')) for p in files))
