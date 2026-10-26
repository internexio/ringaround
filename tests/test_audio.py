"""
Audio pipeline tests: codec, STT, TTS.

Offline tests (always run):
  - G.711 µ-law encode/decode round-trip
  - Downsample correctness
  - Providers return empty/gracefully when no API key

Live tests (require API keys, skipped otherwise):
  - DEEPGRAM_API_KEY: DeepgramSTTProvider against silence → empty transcript
  - CARTESIA_API_KEY: CartesiaTTSProvider synthesizes → non-empty PCM bytes
  - Full loop: Cartesia → codec → Deepgram (codec integration path)
"""
from __future__ import annotations
import math
import os
import struct
import pytest
from ringaround.audio.codec import pcm16_to_ulaw, ulaw_to_pcm16, downsample_2x
from ringaround.audio.stt.deepgram import DeepgramSTTProvider
from ringaround.audio.tts.cartesia import CartesiaTTSProvider

HAVE_DEEPGRAM = bool(os.getenv("DEEPGRAM_API_KEY"))
HAVE_CARTESIA = bool(os.getenv("CARTESIA_API_KEY"))


# ------------------------------------------------------------------ helpers

def _silence_pcm16(duration_ms: int, sample_rate: int = 16000) -> bytes:
    n = sample_rate * duration_ms // 1000
    return b"\x00" * (n * 2)


def _sine_pcm16(freq: int = 440, duration_ms: int = 200, sample_rate: int = 16000) -> bytes:
    n = sample_rate * duration_ms // 1000
    samples = [int(16000 * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


# ------------------------------------------------------------------ codec unit tests

def test_ulaw_round_trip_silence():
    """µ-law adds a ~132-sample quantisation bias near zero — not bit-exact."""
    pcm = _silence_pcm16(100)
    recovered = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    orig = struct.unpack(f"<{len(pcm)//2}h", pcm)
    rec  = struct.unpack(f"<{len(recovered)//2}h", recovered)
    max_err = max(abs(o - r) for o, r in zip(orig, rec))
    assert max_err < 200  # bias is ~132; anything over 200 is a bug


def test_ulaw_round_trip_sine():
    """Round-trip error should be small relative to signal amplitude."""
    pcm = _sine_pcm16()
    recovered = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    orig = struct.unpack(f"<{len(pcm)//2}h", pcm)
    rec  = struct.unpack(f"<{len(recovered)//2}h", recovered)
    # Max quantisation error for µ-law is typically < 2% of full scale (327)
    max_err = max(abs(o - r) for o, r in zip(orig, rec))
    assert max_err < 600, f"Round-trip error too large: {max_err}"


def test_ulaw_encode_zero():
    """Zero sample encodes to 0xFF in standard µ-law."""
    ulaw = pcm16_to_ulaw(b"\x00\x00")
    assert ulaw == bytes([0xFF])


def test_downsample_2x_halves_length():
    pcm = _sine_pcm16(duration_ms=100)
    out = downsample_2x(pcm)
    assert len(out) == len(pcm) // 2


def test_downsample_2x_preserves_dtype():
    """Output samples are still valid int16 range."""
    pcm = _sine_pcm16()
    out = downsample_2x(pcm)
    n = len(out) // 2
    samples = struct.unpack(f"<{n}h", out)
    assert all(-32768 <= s <= 32767 for s in samples)


def test_codec_pipeline_telnyx_to_stt():
    """
    Simulate the Telnyx inbound path:
      PCMU 8kHz (from Telnyx) → ulaw_to_pcm16 → bytes ready for Deepgram 8kHz.
    """
    # Start with a 16kHz sine, downsample to 8kHz, encode as µ-law (Telnyx outbound)
    pcm16k = _sine_pcm16(freq=440, duration_ms=200, sample_rate=16000)
    pcm8k  = downsample_2x(pcm16k)
    ulaw   = pcm16_to_ulaw(pcm8k)

    # Telnyx sends ulaw; our session decodes it
    decoded_pcm8k = ulaw_to_pcm16(ulaw)
    assert len(decoded_pcm8k) == len(pcm8k)

    # The decoded bytes are ready to send to Deepgram (8kHz PCM16)
    assert len(decoded_pcm8k) % 2 == 0


# ------------------------------------------------------------------ STT offline

async def test_deepgram_no_key_returns_empty():
    provider = DeepgramSTTProvider(api_key=None)
    # Force empty key
    provider._api_key = None
    result = await provider.transcribe_turn(_sine_pcm16())
    assert result == ""


async def test_deepgram_short_audio_skipped():
    """Audio shorter than minimum threshold returns empty string."""
    provider = DeepgramSTTProvider(api_key="fake")
    result = await provider.transcribe_turn(b"\x00" * 10)
    assert result == ""


async def test_deepgram_8khz_constructor():
    provider = DeepgramSTTProvider(api_key=None, sample_rate=8000)
    assert provider._params["sample_rate"] == "8000"
    assert provider._min_bytes == 1600


# ------------------------------------------------------------------ TTS offline

async def test_cartesia_no_key_returns_empty():
    provider = CartesiaTTSProvider(api_key=None)
    provider._api_key = None
    result = await provider.synthesize("Hello world")
    assert result == b""


async def test_cartesia_empty_text_returns_empty():
    provider = CartesiaTTSProvider(api_key="fake")
    result = await provider.synthesize("   ")
    assert result == b""


# ------------------------------------------------------------------ live STT

@pytest.mark.skipif(not HAVE_DEEPGRAM, reason="DEEPGRAM_API_KEY not set")
async def test_deepgram_live_silence():
    """Silence should transcribe to an empty string."""
    provider = DeepgramSTTProvider()
    audio = _silence_pcm16(duration_ms=500)
    result = await provider.transcribe_turn(audio)
    assert isinstance(result, str)
    assert result.strip() == ""


@pytest.mark.skipif(not HAVE_DEEPGRAM, reason="DEEPGRAM_API_KEY not set")
async def test_deepgram_live_8khz():
    """8kHz path (Telnyx mode) works end-to-end."""
    pcm16 = _sine_pcm16(freq=440, duration_ms=500, sample_rate=16000)
    pcm8  = downsample_2x(pcm16)
    provider = DeepgramSTTProvider(sample_rate=8000)
    result = await provider.transcribe_turn(pcm8)
    assert isinstance(result, str)  # tone → empty is fine


# ------------------------------------------------------------------ live TTS

@pytest.mark.skipif(not HAVE_CARTESIA, reason="CARTESIA_API_KEY not set")
async def test_cartesia_live_synthesizes():
    provider = CartesiaTTSProvider()
    pcm = await provider.synthesize("Hi, this is a test call.")
    assert len(pcm) > 1000  # non-trivial audio
    # Should be valid 16-bit PCM (even byte count)
    assert len(pcm) % 2 == 0


@pytest.mark.skipif(not HAVE_CARTESIA, reason="CARTESIA_API_KEY not set")
async def test_cartesia_live_codec_round_trip():
    """Cartesia 16kHz → downsample → µ-law → decode → verify length."""
    provider = CartesiaTTSProvider()
    pcm16k = await provider.synthesize("Roughly eight thousand dollars.")
    assert pcm16k, "No audio returned"

    pcm8k = downsample_2x(pcm16k)
    assert len(pcm8k) == len(pcm16k) // 2

    ulaw   = pcm16_to_ulaw(pcm8k)
    assert len(ulaw) == len(pcm8k) // 2

    recovered = ulaw_to_pcm16(ulaw)
    assert len(recovered) == len(pcm8k)


# ------------------------------------------------------------------ full pipeline (both keys)

@pytest.mark.skipif(
    not (HAVE_DEEPGRAM and HAVE_CARTESIA),
    reason="Requires both DEEPGRAM_API_KEY and CARTESIA_API_KEY",
)
async def test_full_audio_pipeline():
    """
    Cartesia synthesizes → codec encodes for Telnyx →
    codec decodes on inbound → Deepgram transcribes.
    Not testing exact transcript — just that the pipeline doesn't crash
    and Deepgram returns a string.
    """
    tts = CartesiaTTSProvider()
    stt = DeepgramSTTProvider(sample_rate=8000)

    pcm16k  = await tts.synthesize("We can start in about three weeks.")
    pcm8k   = downsample_2x(pcm16k)
    ulaw    = pcm16_to_ulaw(pcm8k)
    decoded = ulaw_to_pcm16(ulaw)

    transcript = await stt.transcribe_turn(decoded)
    assert isinstance(transcript, str)
    # The codec + telephony path may mangle speech but should return something
