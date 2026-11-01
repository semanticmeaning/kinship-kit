#!/usr/bin/env python3
"""Запуск CLI без установки: python3 <папка навыка>/kin.py <команда>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kin.cli import main  # noqa: E402

sys.exit(main())
