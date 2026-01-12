"""mcp_pandoc package initialization."""
from . import config
from . import server
from .cli import main

__version__ = "0.9.0"

# Optionally expose other important items at package level
__all__ = ['main', 'server', 'config', '__version__']
