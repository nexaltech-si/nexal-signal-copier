"""
Simulator package.

Names are loaded on first use, not on import: the engine and the service pull in
the bot's settings, and the replay worker and the full-flow session must be able
to prepare their environment before those are read.
"""
__all__ = [
    "SimulatedTrade",
    "SimulationResults",
    "TradingSimulator",
    "simulator_service",
]


def __getattr__(name):
    if name in ("SimulatedTrade", "SimulationResults"):
        from simulator import models
        return getattr(models, name)
    if name == "TradingSimulator":
        from simulator.engine import TradingSimulator
        return TradingSimulator
    if name == "simulator_service":
        from simulator.service import simulator_service
        return simulator_service
    raise AttributeError(f"module 'simulator' has no attribute {name!r}")
