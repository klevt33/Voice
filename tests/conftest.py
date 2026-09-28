"""Pytest configuration for the test suite."""
import os

import pytest

# Hardware probe scripts, not unit tests.
#
# These files are named test_*.py but contain no assertions at all: their
# functions open the real microphone/speakers, print a report and return a bool.
# pytest collects them purely because of the filename, and they block forever
# inside pyaudio's stream.read() waiting for audio from a device that is not
# producing any.  They are still useful as manual diagnostics, so they are
# excluded from the suite rather than deleted.
#
# Run one by hand instead:
#     .\.venv\Scripts\python.exe tests\test_device_detection.py
collect_ignore = [
    "test_device_detection.py",
    "test_audio_reconnection.py",
    "test_end_to_end_audio.py",
    "test_others_audio_quality.py",
]

# Tests that build real Tk widgets.
_TK_DEPENDENT = {
    "test_ui_exception_status.py",
    "test_topic_storage_integration.py",
}


def _tkinter_usable() -> bool:
    """
    Check whether a Tk root can actually be created.

    The project venv is based on the Microsoft Store build of Python, whose Tcl
    and Tk data files live under WindowsApps and are not always readable by the
    test process.  When they are not, tkinter.Tk() raises "Can't find a usable
    init.tcl" - intermittently, which makes the GUI tests fail at random.
    """
    try:
        import tkinter
    except Exception:
        return False
    try:
        root = tkinter.Tk()
    except Exception:
        return False
    try:
        root.destroy()
    except Exception:
        pass
    return True


_TK_UNAVAILABLE = not _tkinter_usable()


def pytest_collection_modifyitems(config, items):
    """Skip widget tests when Tk cannot start, instead of failing at random."""
    if not _TK_UNAVAILABLE:
        return
    reason = pytest.mark.skip(
        reason="Tk/Tcl cannot start in this environment (see tests/conftest.py); "
        "the WindowsApps Python build cannot always read its Tcl data files"
    )
    for item in items:
        if os.path.basename(str(item.fspath)) in _TK_DEPENDENT:
            item.add_marker(reason)
