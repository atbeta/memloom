"""Admin HTTP API for the Memloom dashboard."""

from .router import build_admin_router
from .state import AdminState

__all__ = ["AdminState", "build_admin_router"]
