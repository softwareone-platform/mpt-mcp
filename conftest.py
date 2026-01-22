"""
Pytest configuration file.

This file ensures that the project root is in the Python path,
allowing tests to import from the src package.
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
