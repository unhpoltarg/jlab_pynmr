"""Launch settings for the UNH DAQ computer (feature ``lab-env``).

PyNMR runs inside WSL there. Under WSLg, Qt's drop-down lists (the Event Label and Quadrature sequence boxes)
were sometimes not drawn, although clicks still landed on them (Ells, 2026-11-10). Qt's X11 backend (xcb) draws
them, so inside WSL PyNMR uses xcb unless QT_QPA_PLATFORM is already set. Other computers are left alone.
"""
import os
import sys


def in_wsl(environ=None, platform=None, proc_version='/proc/version'):
    """True when running under the Windows Subsystem for Linux."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if not platform.startswith('linux'):
        return False
    if environ.get('WSL_DISTRO_NAME') or environ.get('WSL_INTEROP'):
        return True
    try:
        with open(proc_version) as f:
            return 'microsoft' in f.read().lower()
    except OSError:
        return False


def prefer_xcb_on_wsl(environ=None, platform=None, proc_version='/proc/version'):
    """Inside WSL, set QT_QPA_PLATFORM=xcb unless it's already set or there is no X display.
    Call before the QApplication is created.

    Returns:
        'xcb' if it set the variable, else None
    """
    environ = os.environ if environ is None else environ
    if environ.get('QT_QPA_PLATFORM') or not environ.get('DISPLAY'):
        return None
    if not in_wsl(environ, platform, proc_version):
        return None
    environ['QT_QPA_PLATFORM'] = 'xcb'
    print('PyNMR: running in WSL, so using Qt\'s xcb display backend (drop-down lists are drawn reliably). '
          'Set QT_QPA_PLATFORM to override.')
    return 'xcb'
