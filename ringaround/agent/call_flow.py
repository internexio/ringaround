"""
Call flow state machine.

Each call runs through: DIALING → INTRO → CONFIRM_PROJECT → QUOTE_ASK
→ FOLLOW_UP → CLOSE → COMPLETED, with early exits to terminal states
based on vendor intent.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
from ringaround.models import (
    CallState, TurnIntent, Turn, CallResult, Contractor,
    ProjectRequest, TERMINAL_STATES,
)
from ringaround.telephony.base import TelephonyProvider
from ringaround.audio.stt.base import STTProvider
from ringaround.audio.tts.base import TTSProvider
from ringaround.llm.base import LLMProvider
from ringaround.agent.extractor import extract_quote


# Max vendor turns per state before giving up
MAX_UNCLEAR_RETRIES = 2
# Max follow-up questions to ask
MAX_FOLLOW_UP_TURNS = 2


class CallFlow:
    def __init__(
        self,
        telephony: TelephonyProvider,
        stt: STTProvider,
        tts: TTSProvider,
        llm: LLMProvider,
    ):
        self.telephony = telephony
        self.stt = stt
        self.tts = tts
        self.llm = llm

    async def run(
        self,
        contractor: Contractor,
        project: ProjectRequest,
        job_id: str,
    ) -> CallResult:
        result = CallResult(
            job_id=job_id,
            contractor=contractor,
            final_state=CallState.DIALING,
            started_at=datetime.utcnow(),
        )

        persona = contractor.mock_persona
        session = await self.telephony.dial(
            contractor.phone,
            context={"mock_persona": persona},
        )

        if session is None:
            result.final_state = CallState.NO_ANSWER
            result.ended_at = datetime.utcnow()
            return result

        try:
            await self._run_session(session, result, project, persona)
        except Exception as exc:
            result.final_state = CallState.FAILED
            result.turns.append(Turn(
                state=result.final_state,
                agent_text=f"[error: {exc}]",
            ))
        finally:
            await session.hang_up()
            result.ended_at = datetime.utcnow()
            if result.ended_at and result.started_at:
                result.duration_seconds = (
                    result.ended_at - result.started_at
                ).total_seconds()

        result.quote = await extract_quote(result)
        return result

    async def _run_session(self, session, result, project, persona):
        follow_up_count = 0
        unclear_count = 0
        state = CallState.INTRO

        while state not in TERMINAL_STATES:
            agent_text = await self.llm.generate_agent_turn(state, project, {})
            audio = await self.tts.synthesize(agent_text)
            await session.send_audio(audio)

            # CLOSE is a one-way exit — emit goodbye, don't wait for vendor
            if state == CallState.CLOSE:
                result.turns.append(Turn(state=state, agent_text=agent_text))
                result.final_state = CallState.COMPLETED
                return

            stt_hint = f"{persona}:{state.value}"
            vendor_audio = await self._collect_turn_audio(session)
            vendor_text = await self.stt.transcribe_turn(vendor_audio, hint=stt_hint)

            intent = TurnIntent.HUNG_UP
            if vendor_text.strip():
                intent = await self.llm.classify_intent(vendor_text, state)

            result.turns.append(Turn(
                state=state,
                agent_text=agent_text,
                vendor_text=vendor_text or None,
                intent=intent,
            ))

            state = self._transition(state, intent, follow_up_count, unclear_count)

            # Retry overrides only apply to non-terminal intermediate states
            if state not in TERMINAL_STATES:
                if state == CallState.FOLLOW_UP:
                    follow_up_count += 1
                    if follow_up_count >= MAX_FOLLOW_UP_TURNS:
                        state = CallState.CLOSE

                if intent == TurnIntent.UNCLEAR:
                    unclear_count += 1
                    if unclear_count >= MAX_UNCLEAR_RETRIES:
                        state = CallState.CLOSE
                else:
                    unclear_count = 0

        result.final_state = state

    async def _collect_turn_audio(self, session, max_silence_ms: int = 1500) -> bytes:
        chunks = []
        async for chunk in session.receive_audio():
            chunks.append(chunk)
            if len(chunks) >= 15:  # ~1.5s at 100ms chunks
                break
        return b"".join(chunks)

    def _transition(
        self,
        state: CallState,
        intent: TurnIntent,
        follow_up_count: int,
        unclear_count: int,
    ) -> CallState:
        # Universal exits regardless of state
        if intent == TurnIntent.HUNG_UP:
            return CallState.FAILED
        if intent == TurnIntent.CALL_BACK:
            return CallState.CALLBACK_SCHEDULED
        if intent == TurnIntent.REFUSED:
            return CallState.REFUSED
        if intent == TurnIntent.OUT_OF_AREA:
            return CallState.OUT_OF_AREA
        if intent == TurnIntent.UNAVAILABLE:
            return CallState.UNAVAILABLE

        # State-specific transitions
        if state == CallState.INTRO:
            if intent in (TurnIntent.POSITIVE, TurnIntent.NEEDS_MORE_INFO):
                return CallState.CONFIRM_PROJECT
            return CallState.REFUSED

        if state == CallState.CONFIRM_PROJECT:
            if intent in (TurnIntent.POSITIVE, TurnIntent.NEEDS_MORE_INFO):
                return CallState.QUOTE_ASK
            return CallState.REFUSED

        if state == CallState.QUOTE_ASK:
            if intent == TurnIntent.GAVE_QUOTE:
                return CallState.FOLLOW_UP
            if intent == TurnIntent.NEEDS_MORE_INFO:
                return CallState.QUOTE_ASK  # stay, let retry logic handle limit
            return CallState.CLOSE

        if state == CallState.FOLLOW_UP:
            return CallState.FOLLOW_UP  # runner increments counter, forces CLOSE

        if state == CallState.CLOSE:
            return CallState.COMPLETED

        return CallState.COMPLETED
