"""向本机采集服务发送合成 RGB565 帧；仅用于离线网页回归测试。"""
from __future__ import annotations

import argparse
import http.client
import time

WIDTH, HEIGHT = 320, 240


def synthetic_frame(index: int) -> bytes:
    colors = (0xF800, 0x07E0, 0x001F, 0xFFE0, 0xF81F)
    output = bytearray()
    stripe = WIDTH // len(colors)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            value = colors[((x // stripe) + index + y // 48) % len(colors)]
            output.extend(((value >> 8) & 0xFF, value & 0xFF))
    return bytes(output)


def request(port: int, method: str, path: str, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        return response.status, payload
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--frames", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.frames <= 30:
        parser.error("--frames must be in [1,30]")
    status, payload = request(args.port, "GET", "/api/control")
    if status != 200:
        raise SystemExit(f"control failed: HTTP {status} {payload!r}")
    control = dict(line.split("=", 1) for line in payload.decode("ascii").splitlines())
    if control.get("enabled") != "1":
        raise SystemExit("capture is not active; click Start Clip first")
    interval = int(control["interval_ms"])
    epoch = control["epoch"]
    for index in range(args.frames):
        raw = synthetic_frame(index)
        headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(raw)),
                   "X-Device-ID": "ui-synthetic-test", "X-Frame-ID": str(1000 + index),
                   "X-Capture-Ms": str(5000 + index * interval), "X-Width": str(WIDTH),
                   "X-Height": str(HEIGHT), "X-Pixel-Format": "RGB565_BE",
                   "X-Control-Epoch": epoch}
        status, payload = request(args.port, "POST", "/api/frames", raw, headers)
        if status != 201:
            raise SystemExit(f"frame {index} failed: HTTP {status} {payload!r}")
        if index + 1 < args.frames:
            time.sleep(interval / 1000 + 0.03)
    print(f"PASS: uploaded {args.frames} synthetic frames to epoch {epoch}")


if __name__ == "__main__":
    main()
