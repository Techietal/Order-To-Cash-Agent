"""
conftest.py — ensures `backend/` is on sys.path so that
`python -m pytest backend/tests -q` works from the repo root.
"""
import sys
import os

# Insert the backend directory at the front of sys.path so all backend
# packages (api, database, config, etc.) are importable without install.
backend_dir = os.path.join(os.path.dirname(__file__), "..")
backend_dir = os.path.abspath(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
