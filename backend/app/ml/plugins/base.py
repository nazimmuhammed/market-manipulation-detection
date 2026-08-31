"""
Detector plugin interface.

To add a new detection algorithm, drop a new .py file into this folder
(ml/plugins/) containing a class that subclasses Detector. It is picked up
automatically the next time the backend starts - no other file needs to be
touched.
"""
from abc import ABC, abstractmethod


class Detector(ABC):
    name = "unnamed_detector"
    description = "No description provided."

    @abstractmethod
    def score(self, ticker: str, tick: dict, history: list) -> float:
        """Return a 0-100 suspicion score for this tick. Must not raise."""
        raise NotImplementedError