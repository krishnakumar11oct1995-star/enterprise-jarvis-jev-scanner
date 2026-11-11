"""Base Harvester Interface for Project Jarvis."""

from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Tuple, Union

from jarvis.graph.models import Node, Edge


class BaseHarvester(ABC):
    """Abstract base class for metadata harvesters."""

    @abstractmethod
    def harvest(self, source: Union[str, Path]) -> Tuple[List[Node], List[Edge]]:
        """
        Parses source file, directory, or snippet.
        Returns a tuple of (nodes, edges).
        """
        pass
