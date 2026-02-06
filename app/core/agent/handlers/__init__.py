"""
Deterministic Handlers for v2 Multi-Agent Architecture.

These handlers do NOT use AI - they return fixed, safe responses.
Used for cases where AI variability is unacceptable (e.g., crisis).
"""

from app.core.agent.handlers.crisis import CrisisHandler

__all__ = ["CrisisHandler"]
