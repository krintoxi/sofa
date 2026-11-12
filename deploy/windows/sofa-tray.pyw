r"""Sofa for Windows: the app in the notification area (sofa/winapp.py has what it does).

The Start menu's Sofa and "start with Windows" run this file with the Python Sofa for Windows brought along:
    vendor\python\pythonw.exe deploy\windows\sofa-tray.pyw [--background | --first-run | --quit | --status]
"""
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, APP)
os.chdir(APP)

from sofa import winapp  # noqa: E402

if __name__ == "__main__":
    sys.exit(winapp.main())
