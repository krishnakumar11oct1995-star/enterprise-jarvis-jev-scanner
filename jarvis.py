#!/usr/bin/env python3
"""Project Jarvis: Enterprise Architecture & Conflict Radar Engine.

Central entry point and CLI dispatcher.
"""

import sys
import os

# Add local directory to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from jarvis.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
