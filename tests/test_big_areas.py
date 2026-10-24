"""A big drive's survey must not stall the server: its outline (thousands of points) is simplified once, on a worker
thread, rather than again for every Qloo request on the event loop (Render's health check restarted the server)."""
from __future__ import annotations

import asyncio
import math
import threading

from app import catchment as catchment_module
from app.catchment import QLOO_RING_POINTS, Catchment, simplified


def ring_of(points: int, radius_deg: float = 0.1) -> list[tuple[float, float]]:
    ring = [(-97.72 + radius_deg * math.cos(2 * math.pi * i / points), 30.26 + radius_deg * math.sin(2 * math.pi * i / points))
            for i in range(points)]
    return ring + [ring[0]]


def test_the_outline_qloo_reads_is_simplified_once(monkeypatch):
    calls: list[int] = []
    real = catchment_module.simplify_ring

    def counting(ring, *args, **kwargs):
        calls.append(len(ring))
        return real(ring, *args, **kwargs)

    monkeypatch.setattr(catchment_module, "simplify_ring", counting)
    area = Catchment(30.26, -97.72, 15, "street network", ring_of(1200), ring_of(4000, 0.2), travel="drive")
    first, around = area.wkt, area.around_wkt
    for _ in range(50):  # a survey sends the outline with every Qloo request
        assert area.wkt == first and area.around_wkt == around
    assert calls == [1201, 4001]
    assert first.count(",") < QLOO_RING_POINTS and around.count(",") < QLOO_RING_POINTS


def test_a_long_outline_is_simplified_off_the_event_loop(monkeypatch):
    threads: list[str] = []
    real = catchment_module.simplify_ring

    def noting(ring, *args, **kwargs):
        threads.append(threading.current_thread().name)
        return real(ring, *args, **kwargs)

    monkeypatch.setattr(catchment_module, "simplify_ring", noting)
    drive = Catchment(30.26, -97.72, 15, "street network", ring_of(1200), ring_of(4000, 0.2), travel="drive")
    walk = Catchment(40.71, -73.96, 10, "street network", ring_of(30, 0.005), ring_of(80, 0.01))

    async def scenario() -> str:
        await simplified(drive)
        await simplified(walk)
        return threading.current_thread().name

    loop_thread = asyncio.run(scenario())
    assert len(threads) == 2 and loop_thread not in threads  # both of the drive's outlines, on a worker thread
    assert "wkt" in drive.__dict__ and "around_wkt" in drive.__dict__
    assert "wkt" not in walk.__dict__  # a walk's few points are simplified when first read, as before
