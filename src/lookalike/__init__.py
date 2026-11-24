"""lookalike: anonymize structured data while preserving schema and cardinality."""

from .core import Options, anonymize, make_plans
from .io import load, save
from .verify import verify

__version__ = "0.1.3"
__all__ = ["Options", "anonymize", "make_plans", "load", "save", "verify"]
