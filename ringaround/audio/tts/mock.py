import asyncio


class MockTTSProvider:
    async def synthesize(self, text: str) -> bytes:
        await asyncio.sleep(0.02)
        return b"\x00" * max(len(text) * 32, 160)  # silence proportional to text length
