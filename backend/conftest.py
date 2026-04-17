"""
pytest configuration for the TokenProof backend test suite.
Adds the backend/ directory to sys.path so tests can import
engine, canton_adapter, and policy_packs without path manipulation
inside individual test files.

Run from the backend/ directory:
    python -m pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
