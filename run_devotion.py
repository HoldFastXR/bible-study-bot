#!/usr/bin/env python3
"""
run_devotion.py
Cron target for daily devotion generation and distribution.
Called by cron at 6:00 AM every day Mon–Sat.

Crontab entry:
  0 6 * * 1-6 cd /home/daniel/bible-study-bot && /home/daniel/bible-study-bot/venv/bin/python run_devotion.py >> logs/cron.log 2>&1
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from devotion_agent import run

if __name__ == "__main__":
    run()
