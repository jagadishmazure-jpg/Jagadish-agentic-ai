"""Sales meeting prep: parallel research fan-out (Send) -> synthesizer -> one-page brief."""

from meeting_prep.graph import build_graph
from meeting_prep.sources import Sources, seed_sources

__all__ = ["Sources", "build_graph", "seed_sources"]
