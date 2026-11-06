"""Keeps a bug in livekit_ffi.dll from stopping a call. Call harden() once per process, before any audio starts.

soxr builds one global FFT cache on first use, and two threads doing that together trip an assert in the DLL. On Windows
that assert is a modal dialog: the process stops until someone clicks. Offline, 12 racing resamplers killed or hung
3 of 105 cold processes and 0 of 80 warmed ones, so one resampler runs alone first. The dialog check stays as the net.
ponytail: the title match is the DLL's static CRT wording; upgrade when the SDK fixes soxr.
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from livekit import rtc

CRT_TITLE = "Visual C++ Runtime Library"


def warm_resampler():
    r = rtc.AudioResampler(48000, 24000, num_channels=1)
    for _ in range(4):
        r.push(rtc.AudioFrame(bytes(960), 48000, 1, 480))
    r.flush()


def _exit_on_dialog():
    """A dead process can be restarted; one waiting on a click cannot."""
    user32, me = ctypes.windll.user32, os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def check(hwnd, _):
        pid, title = wintypes.DWORD(), ctypes.create_unicode_buffer(64)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me and user32.GetWindowTextW(hwnd, title, 64) and CRT_TITLE in title.value:
            print("native assert dialog: exiting so the process can be restarted", file=sys.stderr, flush=True)
            os._exit(3)
        return True

    while True:
        time.sleep(0.5)
        user32.EnumWindows(check, 0)


def harden():
    warm_resampler()
    if os.name == "nt":
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)   # no Windows fault or missing-file boxes either
        threading.Thread(target=_exit_on_dialog, daemon=True, name="native-dialog-watch").start()
