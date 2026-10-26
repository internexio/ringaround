"""
Provider factory — reads env vars and returns concrete provider instances.
All provider keys default to 'mock' so the system runs offline with no config.

  TELEPHONY_PROVIDER = mock | telnyx
  STT_PROVIDER       = mock | deepgram
  TTS_PROVIDER       = mock | cartesia
  LLM_PROVIDER       = mock | claude | gemini
  DIRECTORY_PROVIDER = mock | google_places

Usage:
    from ringaround.factory import build_call_flow, build_directory
    directory = build_directory()
    contractors = await directory.find_contractors(project)
    flow = build_call_flow()
"""
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()


def build_telephony():
    provider = os.getenv("TELEPHONY_PROVIDER", "mock").lower()
    if provider == "telnyx":
        from ringaround.telephony.telnyx import TelnyxProvider
        return TelnyxProvider()
    from ringaround.telephony.mock import MockTelephonyProvider
    return MockTelephonyProvider()


def build_stt():
    provider = os.getenv("STT_PROVIDER", "mock").lower()
    if provider == "deepgram":
        from ringaround.audio.stt.deepgram import DeepgramSTTProvider
        # Telnyx decodes µ-law to 8kHz PCM before sending to STT
        telephony = os.getenv("TELEPHONY_PROVIDER", "mock").lower()
        sample_rate = 8000 if telephony == "telnyx" else 16000
        return DeepgramSTTProvider(sample_rate=sample_rate)
    from ringaround.audio.stt.mock import MockSTTProvider
    return MockSTTProvider()


def build_tts():
    provider = os.getenv("TTS_PROVIDER", "mock").lower()
    if provider == "cartesia":
        from ringaround.audio.tts.cartesia import CartesiaTTSProvider
        return CartesiaTTSProvider()
    from ringaround.audio.tts.mock import MockTTSProvider
    return MockTTSProvider()


def build_llm():
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider == "claude":
        from ringaround.llm.claude import ClaudeLLMProvider
        return ClaudeLLMProvider()
    if provider in ("gemini", "gemini-flash"):
        from ringaround.llm.gemini import GeminiLLMProvider
        return GeminiLLMProvider()
    from ringaround.llm.mock import MockLLMProvider
    return MockLLMProvider()


def build_directory():
    provider = os.getenv("DIRECTORY_PROVIDER", "mock").lower()
    if provider == "google_places":
        from ringaround.directory.google_places import GooglePlacesProvider
        return GooglePlacesProvider()
    from ringaround.directory.mock import MockDirectoryProvider
    return MockDirectoryProvider()


def build_call_flow():
    from ringaround.agent.call_flow import CallFlow
    return CallFlow(
        telephony=build_telephony(),
        stt=build_stt(),
        tts=build_tts(),
        llm=build_llm(),
    )
