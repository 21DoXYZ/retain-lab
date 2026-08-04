"""Делает корень репозитория импортируемым для pytest (модуль `api`).

`python -m pytest` из корня и так кладёт cwd в sys.path, но при запуске из
другого каталога/через rootdir этого может не случиться — страхуемся явно.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
