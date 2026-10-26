"""
G.711 µ-law (PCMU) codec — pure Python, no deps.

Telnyx delivers 8kHz PCMU audio over WebSocket.
Our TTS stack (Cartesia) produces 16kHz signed-16-bit PCM.

Paths:
  inbound  (Telnyx → STT):  ulaw_to_pcm16()   → pass to Deepgram
  outbound (TTS → Telnyx):  downsample_2x()
                           + pcm16_to_ulaw()   → send to Telnyx WebSocket
"""
from __future__ import annotations
import struct

_BIAS = 0x84
_MAX = 0x7FFF


def pcm16_to_ulaw(pcm_bytes: bytes) -> bytes:
    """Convert 8kHz 16-bit signed PCM → 8-bit G.711 µ-law."""
    out = bytearray(len(pcm_bytes) // 2)
    for i, off in enumerate(range(0, len(pcm_bytes), 2)):
        sample = struct.unpack_from("<h", pcm_bytes, off)[0]
        sign = 0 if sample >= 0 else 0x80
        sample = min(abs(sample) + _BIAS, _MAX)
        exp = 7
        mask = 0x4000
        while exp > 0 and not (sample & mask):
            exp -= 1
            mask >>= 1
        mantissa = (sample >> (exp + 3)) & 0x0F
        out[i] = (~(sign | (exp << 4) | mantissa)) & 0xFF
    return bytes(out)


def ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """Convert 8-bit G.711 µ-law → 8kHz 16-bit signed PCM."""
    out = bytearray(len(ulaw_bytes) * 2)
    for i, byte in enumerate(ulaw_bytes):
        byte = (~byte) & 0xFF
        sign = byte & 0x80
        exp = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        sample = ((mantissa << 3) + _BIAS) << exp
        if sign:
            sample = -sample
        sample = max(-32768, min(32767, sample))
        struct.pack_into("<h", out, i * 2, sample)
    return bytes(out)


def downsample_2x(pcm16_bytes: bytes) -> bytes:
    """Halve sample rate by dropping every other 16-bit sample (16kHz → 8kHz).
    Adequate for voice; not suitable for wideband audio."""
    n = len(pcm16_bytes) // 2
    samples = struct.unpack(f"<{n}h", pcm16_bytes)
    kept = samples[::2]
    return struct.pack(f"<{len(kept)}h", *kept)
