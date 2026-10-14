"""Offline public-source response fixture. Never used by production code."""
from release_core import digest

def fake_source(url):
    text = ('Synthetic public source text for isolated unit testing only. ' * 10)
    return {'url':url,'final_url':url,'http_status':200,'content_type':'text/html',
            'bytes':len(text.encode()),'sha256':digest(text),'text_sha256':digest(text),
            'retrieved_at':'2026-10-14T00:00:00+00:00','text':text,'method':'direct_https'}
