"""Capture only the caller's own test window via WM_PRINT (no desktop capture)."""
import ctypes
from ctypes import wintypes as w


def save_window(widget, target):
    from PIL import Image
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    user.GetDC.argtypes = [w.HWND]
    user.GetDC.restype = w.HDC
    user.ReleaseDC.argtypes = [w.HWND, w.HDC]
    user.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    gdi.CreateCompatibleDC.argtypes = [w.HDC]
    gdi.CreateCompatibleDC.restype = w.HDC
    gdi.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = w.HBITMAP
    gdi.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
    gdi.SelectObject.restype = w.HGDIOBJ
    gdi.DeleteObject.argtypes = [w.HGDIOBJ]
    gdi.DeleteDC.argtypes = [w.HDC]
    gdi.GetBitmapBits.argtypes = [w.HBITMAP, w.LONG, ctypes.c_void_p]
    widget.update()
    hwnd = user.GetAncestor(widget.winfo_id(), 2)
    rect = w.RECT()
    user.GetClientRect(hwnd, ctypes.byref(rect))
    width, height = rect.right, rect.bottom
    dc = user.GetDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    old = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 3):
            raise OSError("PrintWindow failed")
        buffer = ctypes.create_string_buffer(width*height*4)
        if gdi.GetBitmapBits(bitmap, len(buffer), buffer) != len(buffer):
            raise OSError("GetBitmapBits failed")
        Image.frombytes("RGB", (width, height), buffer.raw, "raw", "BGRX").save(target)
    finally:
        gdi.SelectObject(memory, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)
