"""Bounded, pitch-preserving timing correction of already verified narration.

No trimming, padding, text changes, new TTS requests, or acceptance-limit changes.
Only episodes slightly longer than 15 minutes may be accelerated, by at most 15%.
The caller still verifies decoded duration and independently transcribes the end.
"""
from __future__ import annotations
import math

MIN_SECONDS = 540.0
MAX_SECONDS = 900.0
LONG_TARGET_SECONDS = 840.0
MAX_TEMPO = 1.15


def timing_plan(source_seconds: float) -> dict:
    if not math.isfinite(source_seconds) or source_seconds <= 0:
        raise ValueError('Invalid assembled source duration')
    factor = 1.0
    if source_seconds > MAX_SECONDS:
        factor = source_seconds / LONG_TARGET_SECONDS
        if factor > MAX_TEMPO:
            raise RuntimeError('Episode requires more than 15 percent tempo correction; publication blocked')
        factor = round(factor, 8)
    return {'source_duration_seconds': source_seconds, 'tempo_factor': factor,
            'expected_output_seconds': source_seconds / factor,
            'filter': 'atempo' if factor != 1.0 else None,
            'trim_applied': False, 'padding_applied': False,
            'maximum_tempo_factor': MAX_TEMPO}


def encoder_arguments(plan: dict) -> list[str]:
    factor = plan['tempo_factor']
    if not math.isfinite(factor) or not 1.0 <= factor <= MAX_TEMPO:
        raise ValueError('Invalid audio timing factor')
    return ['-af', f'atempo={factor:.8f}'] if factor != 1.0 else []


def validate_output_duration(seconds: float, plan: dict) -> None:
    if not math.isfinite(seconds) or abs(seconds - plan['expected_output_seconds']) > 1:
        raise RuntimeError('Assembled audio duration does not match all decoded segments and timing factor')
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise RuntimeError('Episode audio outside the 9 to 15 minute release limit')
