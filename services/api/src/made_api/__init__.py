"""MADE FastAPI REST API service package."""

from made_api.main import app, create_app

__version__ = "0.1.0"
__all__ = ["app", "create_app", "__version__"]
