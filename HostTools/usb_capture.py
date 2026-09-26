"""USB CDC binary receiver, sharing CaptureStore with the browser/HTTP service.

pyserial is imported only when opening a real USB port. Decoder/tests use stdlib.
Wire format and physical connector are documented in Docs/usb-firedap-20260917.md.
"""
from __future__ import annotations
from dataclasses import dataclass
import secrets
import struct
import threading
import time
import zlib

HEADER = struct.Struct("<4sHHIIIIHHIIIII")
FRAME_BYTES = 153600
BUFFER_LIMIT = 2 * (FRAME_BYTES + HEADER.size)


def encode_control(control: bytes, cookie: int) -> bytes:
    values = dict(line.split("=", 1) for line in control.decode("ascii").splitlines())
    packet = struct.pack("<4sIIII", b"GSCT", int(values["enabled"]),
                         int(values["interval_ms"]), int(values["epoch"]), cookie)
    return packet + struct.pack("<I", zlib.crc32(packet))


@dataclass(frozen=True)
class Frame:
    metadata: dict
    raw: bytes


class FrameDecoder:
    """Bounded fragmented-stream parser; CRC also permits resync after truncation."""
    def __init__(self):
        self.buffer = bytearray()
        self.bad_headers = self.bad_crc = self.discarded_bytes = 0
        self.partial_since = None

    def reset(self):
        self.buffer.clear()
        self.partial_since = None

    def expire(self, now=None):
        now = time.monotonic() if now is None else now
        if self.partial_since is not None and now - self.partial_since > 3.5:
            self.discarded_bytes += len(self.buffer)
            self.reset()

    def feed(self, data: bytes, now=None):
        now = time.monotonic() if now is None else now
        self.expire(now)
        if len(data) + len(self.buffer) > BUFFER_LIMIT:
            self.reset()
            raise ValueError("USB input exceeds bounded frame buffer")
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            start = self.buffer.find(b"GSFR")
            if start < 0:
                # Preserve a possibly fragmented magic suffix only.
                n = max(0, len(self.buffer) - 3)
                self.discarded_bytes += n
                del self.buffer[:n]
                break
            if start:
                self.discarded_bytes += start
                del self.buffer[:start]
            if len(self.buffer) < HEADER.size:
                break
            fields = HEADER.unpack_from(self.buffer)
            (_, version, header_size, size, frame_id, capture_ms, epoch,
             width, height, pixel_format, crc, uid0, uid1, uid2) = fields
            if (version, header_size, size, width, height, pixel_format) != (1, 48, FRAME_BYTES, 320, 240, 1):
                self.bad_headers += 1
                del self.buffer[0]
                self.partial_since = None
                continue
            end = HEADER.size + size
            if len(self.buffer) < end:
                break
            raw = bytes(self.buffer[HEADER.size:end])
            if zlib.crc32(raw) != crc:
                self.bad_crc += 1
                # A new valid header may sit inside a truncated previous frame.
                del self.buffer[0]
                self.partial_since = None
                continue
            del self.buffer[:end]
            frames.append(Frame(dict(device_id=f"usb-{uid0:08x}{uid1:08x}{uid2:08x}",
                                     frame_id=frame_id, capture_ms=capture_ms, epoch=epoch), raw))
            self.partial_since = None
        if self.buffer and self.partial_since is None:
            self.partial_since = now
        return frames


class USBReceiver:
    def __init__(self, store, port, *, serial_factory=None, api_error_type=None):
        if serial_factory is None:
            import serial
            from serial.tools.list_ports import comports
            for candidate in comports():
                if (candidate.device.casefold() == port.casefold()
                        and (candidate.vid, candidate.pid) == (0x1fc9, 0x5601)):
                    raise ValueError("该 COM 口属于 fireDAP 调试器。图像采集请使用板卡 J38 USB MINI 枚举出的 STM32 CDC 端口。")
            serial_factory = serial.Serial
        if api_error_type is None:
            from capture_server import ApiError
            api_error_type = ApiError
        self.store, self.port, self.factory = store, port, serial_factory
        self.auto_port = port == 'auto'
        self.connected_port = None
        self.api_error_type = api_error_type
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="USB-capture", daemon=True)
        self.accepted = self.rejected = 0
        self.saved = self.duplicates = 0
        self.previewed = 0
        self._diagnostic_lock = threading.Lock()
        self._diagnostics = dict(state="idle", connected=False, last_error=None,
                                 bad_headers=0, bad_crc=0, discarded_bytes=0)
        self.decoder = FrameDecoder()
        self.last_accepted = None
        self.blocked_identity = None

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=6)

    def snapshot(self):
        """Copy published diagnostics; never accesses the port or CaptureStore.

        This lock is held only to copy/update small scalar values, never while
        parsing, doing serial/storage I/O, or holding the store's lock.
        """
        with self._diagnostic_lock:
            return dict(self._diagnostics, port=self.connected_port or self.port, accepted=self.accepted,
                        rejected=self.rejected, saved=self.saved, duplicates=self.duplicates,
                        previewed=self.previewed)

    def _connection_state(self, state, error=None):
        with self._diagnostic_lock:
            self._diagnostics.update(state=state, connected=state == "connected")
            if error is not None:
                self._diagnostics["last_error"] = str(error)
            elif state == "connected":
                self._diagnostics["last_error"] = None

    def feed(self, data):
        # The receive thread owns the decoder. Publish counters after parsing,
        # so HTTP snapshots never wait on a frame CRC or stream resync.
        try:
            return self.decoder.feed(data)
        finally:
            with self._diagnostic_lock:
                self._diagnostics.update(bad_headers=self.decoder.bad_headers,
                                         bad_crc=self.decoder.bad_crc,
                                         discarded_bytes=self.decoder.discarded_bytes)

    def accept(self, frame):
        # Epoch is latched by the board before copying pixels. begin/commit both
        # check it, so a stop while USB bytes are in flight cannot relabel them.
        ticket = None
        try:
            ticket = self.store.begin(frame.metadata)
            if ticket.get("preview_only"):
                status, _ = self.store.commit(ticket, frame.raw)
                with self._diagnostic_lock:
                    self.previewed += 1
                return status
            identity = ticket["session"]["session_id"], ticket["device_id"]
            current = identity + (ticket["frame_id"], ticket["capture_ms"])
            old = self.last_accepted
            rollback = False
            if old is not None and old[:2] == identity:
                id_delta = (current[2] - old[2]) & 0xffffffff
                ms_delta = (current[3] - old[3]) & 0xffffffff
                rollback = (id_delta >= 0x80000000 or ms_delta >= 0x80000000
                            or (id_delta == 0 and ms_delta != 0))
            if rollback or self.blocked_identity == identity:
                # A native USB reboot can retain its Windows COM number. Prevent
                # a reset from silently combining two frame-counter lifetimes.
                self.blocked_identity = identity
                with self.store.lock:
                    if self.store.active_clip is not None:
                        self.store.clip_action(dict(action="stop"))
                    self.store.last_error = "检测到板卡帧号或时间回退，已停止录制。请结束当前会话并新建会话。"
                raise self.api_error_type(409, "board_reset", self.store.last_error)
            status, _ = self.store.commit(ticket, frame.raw)
            if status == 201:
                self.last_accepted = current
                self.blocked_identity = None
            with self._diagnostic_lock:
                self.accepted += 1
                self.saved += int(status == 201)
                self.duplicates += int(status == 200)
            return status
        except self.api_error_type as error:
            with self._diagnostic_lock:
                self.rejected += 1
            return error.status
        finally:
            if ticket is not None:
                self.store.release(ticket)

    def disconnected(self, error):
        self._connection_state("disconnected", error)
        with self.store.lock:
            if self.store.active_clip is not None:
                self.store.clip_action(dict(action="stop"))
            self.store.last_error = f"USB 采集连接失败：{error}。重连后先检查板卡；若已复位请新建会话。"
        print(self.store.last_error, flush=True)

    def run(self):
        while not self.stop_event.is_set():
            try:
                port = self.port
                if self.auto_port:
                    from serial.tools.list_ports import comports
                    candidates = [p.device for p in comports() if (p.vid, p.pid) == (0x0483, 0x5740)]
                    if len(candidates) != 1:
                        self._connection_state('waiting', '请连接开发板 Device USB' if not candidates else '检测到多块板卡，请仅连接需要采集的一块')
                        self.stop_event.wait(1)
                        continue
                    port = candidates[0]
                self.connected_port = port
                self._connection_state("connecting")
                with self.factory(port, baudrate=115200, timeout=0.05,
                                  write_timeout=0.25, rtscts=False, dsrdtr=False) as link:
                    link.reset_input_buffer()
                    self.decoder.reset()
                    self._connection_state("connected")
                    cookie = secrets.randbits(32)
                    next_control = 0
                    print(f"USB 已打开 {self.port}；等待网页开始录制。", flush=True)
                    while not self.stop_event.is_set():
                        now = time.monotonic()
                        if now >= next_control:
                            packet = encode_control(self.store.control(), cookie)
                            if link.write(packet) != len(packet):
                                raise OSError("USB control write was truncated")
                            next_control = now + 0.25
                        chunk = link.read(min(16384, max(1, link.in_waiting)))
                        for frame in self.feed(chunk):
                            self.accept(frame)
            except (OSError, ValueError) as error:
                self.disconnected(error)
                self.stop_event.wait(1)
        self._connection_state("stopped")


def list_ports():
    from serial.tools.list_ports import comports
    for port in comports():
        print(f"{port.device}: {port.description} [{port.hwid}]")
