"""Media cache work must not block the API loop or outlive its owner."""
import asyncio
import base64
import builtins
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services.file_cache import FileCache


DATA = b"synthetic-media-content"
ENCODED = base64.b64encode(DATA).decode()


async def wait_for_thread(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 2), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "video", "download"])
async def test_media_write_allows_event_loop_progress(tmp_path, kind):
    cache = FileCache(str(tmp_path))
    started, loop_ran = threading.Event(), threading.Event()
    write_threads, loop_progress = [], []
    real_open = builtins.open
    loop_thread = threading.get_ident()

    class Writer:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def write(self, data):
            write_threads.append(threading.get_ident())
            started.set()
            loop_progress.append(loop_ran.wait(0.15))
            return self.file.write(data)

    def open_file(path, *args, **kwargs):
        file = real_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        return Writer(file) if Path(path).parent == tmp_path and "w" in mode else file

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, content=DATA)

    async def tick():
        while not started.is_set():
            await asyncio.sleep(0.001)
        loop_ran.set()

    monitor = asyncio.create_task(tick())
    try:
        with patch("builtins.open", side_effect=open_file), patch(
            "src.services.file_cache.AsyncSession", Session
        ):
            if kind == "download":
                filename = await cache.download_and_cache("https://media.invalid/video.mp4", "video")
            else:
                filename = await getattr(cache, "cache_base64_" + kind)(ENCODED)
            await asyncio.wait_for(monitor, 2)
        assert write_threads and all(thread != loop_thread for thread in write_threads)
        assert all(loop_progress), "The API event loop stopped while a media file was written"
        assert (tmp_path / filename).read_bytes() == DATA
        assert not cache._active_download_paths
        assert list(tmp_path.iterdir()) == [tmp_path / filename]
    finally:
        if not monitor.done():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "video"])
async def test_cancelled_cache_write_keeps_staging_owned_until_worker_stops(tmp_path, kind):
    cache = FileCache(str(tmp_path), default_timeout=1)
    entered, release = threading.Event(), threading.Event()
    native_write = cache._write_cached_content

    def write(path, content):
        inner = path.with_suffix(path.suffix + ".part")
        inner.write_bytes(b"partial")
        os.utime(inner, (1, 1))
        entered.set()
        if not release.wait(3):
            raise TimeoutError("Test did not release worker")
        native_write(path, content)

    task = None
    with patch.object(cache, "_write_cached_content", side_effect=write):
        try:
            task = asyncio.create_task(getattr(cache, "cache_base64_" + kind)(ENCODED))
            await wait_for_thread(entered)
            await cache._cleanup_expired_files()
            assert any(tmp_path.iterdir()), "Cleanup removed an active staging file"
            assert await cache.clear_all() == 0
            assert any(tmp_path.iterdir()), "Manual clear removed an active staging file"
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done(), "Running write lost ownership after cancellation"
            assert all(path.name.endswith(".part") for path in tmp_path.iterdir())
        finally:
            release.set()
            if task is not None:
                result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(result, asyncio.CancelledError)
    assert not list(tmp_path.iterdir()), "Cancelled work published a late cache file"
    assert not cache._active_download_paths
    filename = await cache.cache_base64_video(ENCODED)
    assert (tmp_path / filename).read_bytes() == DATA


@pytest.mark.asyncio
async def test_cache_workers_are_bounded_and_cancelled_queue_does_not_write(tmp_path):
    cache = FileCache(str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    state_lock = threading.Lock()
    active = peak = 0
    written = []
    native_write = cache._write_cached_content

    def write(path, data):
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
            written.append(data)
            if active == 4:
                entered.set()
        try:
            if not release.wait(3):
                raise TimeoutError("Test did not release workers")
            native_write(path, data)
        finally:
            with state_lock:
                active -= 1

    tasks = []
    with patch.object(cache, "_write_cached_content", side_effect=write):
        try:
            tasks = [asyncio.create_task(cache.cache_base64_video(
                base64.b64encode(f"job-{i}".encode()).decode()
            )) for i in range(12)]
            await wait_for_thread(entered)
            tasks[8].cancel()
            await asyncio.sleep(0)
            assert peak <= 4
        finally:
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
    assert peak == 4
    assert isinstance(results[8], asyncio.CancelledError)
    assert b"job-8" not in written
    assert len([r for r in results if isinstance(r, str)]) == 11
    assert not cache._active_download_paths


@pytest.mark.asyncio
async def test_failed_write_cleans_staging_and_releases_capacity(tmp_path):
    cache = FileCache(str(tmp_path))

    def fail(path, content):
        path.with_suffix(path.suffix + ".part").write_bytes(b"partial")
        raise OSError("synthetic full disk")

    with patch.object(cache, "_write_cached_content", side_effect=fail):
        with pytest.raises(Exception, match="synthetic full disk"):
            await cache.cache_base64_video(ENCODED)
    assert not cache._active_download_paths
    assert not list(tmp_path.iterdir())
    assert (tmp_path / await cache.cache_base64_video(ENCODED)).read_bytes() == DATA


@pytest.mark.asyncio
async def test_cancel_before_executor_start_does_not_run_late_write(tmp_path):
    cache = FileCache(str(tmp_path))
    loop = asyncio.get_running_loop()
    native_executor = loop.run_in_executor
    entered, release = threading.Event(), threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)

    def blocker():
        entered.set()
        release.wait(2)

    occupied = native_executor(executor, blocker)
    while not entered.is_set():
        await asyncio.sleep(0.001)

    def run(pool, fn, *args):
        return native_executor(executor if pool is None else pool, fn, *args)

    try:
        with patch.object(loop, "run_in_executor", side_effect=run), patch.object(
            cache, "_write_cached_content", wraps=cache._write_cached_content
        ) as write:
            task = asyncio.create_task(cache.cache_base64_image(ENCODED))
            await asyncio.sleep(0.01)
            start = time.monotonic()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            assert time.monotonic() - start < 0.5
            assert not cache._active_download_paths
            release.set()
            await occupied
            executor.shutdown(wait=True)
            write.assert_not_called()
            assert not list(tmp_path.iterdir())
    finally:
        release.set()
        await occupied
        executor.shutdown(wait=True)
