import asyncio

import pytest

from services.audio_queue import AudioQueue


def run(coro):
    return asyncio.run(coro)


async def collect(queue: AudioQueue, chunk_size: int = 1280) -> list[bytes]:
    return [chunk async for chunk in queue.consume(chunk_size)]


def test_enqueue_and_consume() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        pcm = bytes(range(64)) * 50
        await queue.enqueue(pcm)
        chunks = await collect(queue)
        assert b"".join(chunks) == pcm
        assert not queue.peek()

    run(scenario())

def test_consume_empty_blocks_until_enqueue() -> None:
    async def scenario() -> None:
        queue = AudioQueue(wait_timeout=1)
        consumer = asyncio.create_task(collect(queue))
        await asyncio.sleep(0)
        assert not consumer.done()
        await queue.enqueue(b"\x00\x01")
        assert await consumer == [b"\x00\x01"]

    run(scenario())


def test_consume_second_client_rejected() -> None:
    async def scenario() -> None:
        queue = AudioQueue(wait_timeout=1)
        first = queue.consume()
        waiting = asyncio.create_task(anext(first))
        await asyncio.sleep(0)

        second = queue.consume()
        with pytest.raises(RuntimeError, match="stream ativo"):
            await anext(second)

        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        await first.aclose()

    run(scenario())


def test_reenqueue_replaces_pending() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        await queue.enqueue(b"\x00\x01")
        await queue.enqueue(b"\x02\x03")
        assert b"".join(await collect(queue)) == b"\x02\x03"

    run(scenario())


def test_consume_disconnect_preserves_audio() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        pcm = b"\x01\x02" * 2000
        await queue.enqueue(pcm)
        stream = queue.consume(chunk_size=1280)
        assert await anext(stream) == pcm[:1280]
        await stream.aclose()
        assert queue.peek()
        assert b"".join(await collect(queue)) == pcm

    run(scenario())


def test_empty_enqueue_rejected() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="payload vazio"):
            await AudioQueue().enqueue(b"")

    run(scenario())


def test_consume_respects_chunk_size() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        await queue.enqueue(b"a" * 10)
        assert await collect(queue, 4) == [b"a" * 4, b"a" * 4, b"a" * 2]

    run(scenario())


def test_consume_large_audio() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        pcm = b"\x00\x01" * 100_000
        await queue.enqueue(pcm)
        chunks = await collect(queue)
        assert b"".join(chunks) == pcm
        assert max(map(len, chunks)) == 1280

    run(scenario())


def test_peek_returns_correct_state() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        assert not queue.peek()
        await queue.enqueue(b"\x00\x01")
        assert queue.peek()
        await collect(queue)
        assert not queue.peek()

    run(scenario())


def test_enqueue_during_stream_is_kept_for_next_request() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        first_pcm = b"\x00\x01" * 1000
        next_pcm = b"\x02\x03" * 10
        await queue.enqueue(first_pcm)

        stream = queue.consume(chunk_size=1280)
        first_chunk = await anext(stream)
        await queue.enqueue(next_pcm)
        remainder = [chunk async for chunk in stream]

        assert b"".join([first_chunk, *remainder]) == first_pcm
        assert queue.peek()
        assert b"".join(await collect(queue)) == next_pcm

    run(scenario())
