"""Wait helper shared by the monitoring loops."""
import asyncio


async def wait_stop_or_change(stop_event: asyncio.Event, provider, timeout: float, min_gap: float = 0.3) -> None:
    """
    Sleep until `timeout` elapses, the stop event is set, or the provider streams a
    structural change (position/order/deal). Providers without push return after
    `timeout`, so behaviour there is unchanged. `min_gap` debounces event bursts.
    """
    if stop_event.is_set():
        return
    if not getattr(provider, "live_reads", False):
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return

    stop = asyncio.ensure_future(stop_event.wait())
    change = asyncio.ensure_future(provider.wait_for_change(timeout))
    try:
        done, _ = await asyncio.wait({stop, change}, return_when=asyncio.FIRST_COMPLETED)
        if change in done and not stop_event.is_set():
            await asyncio.sleep(min_gap)
    finally:
        for t in (stop, change):
            if not t.done():
                t.cancel()
