"""GestureScreen USB/局域网采集服务：手势视频片段、采后标注和训练清单。"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import zlib

# ManagedCaptureStore imports this module; keep the exception/base class identity
# when the server is started as a script rather than imported by the EXE.
if __name__ == '__main__':
    sys.modules['capture_server'] = sys.modules[__name__]

LABELS = ("POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "OTHER", "EMPTY")
LABEL_NAMES = {
    "POINT_LEFT": "指向左侧", "POINT_RIGHT": "指向右侧", "FIST": "握拳",
    "PALM": "张开手掌", "V_SIGN": "V字手势", "OTHER": "其他手势", "EMPTY": "无手",
}
PENDING_LABEL = "__PENDING_CLIP_LABEL__"
SPLITS = ("train", "validation", "calibration", "test")
PREPROCESSING = "rgb565-roi192-gray96-v1"
WIDTH, HEIGHT, FRAME_BYTES = 320, 240, 153600
# Classic RIFF AVI: fixed headers minus 8 bytes + (BGR24 + chunk + idx1) per frame.
AVI_FRAME_BYTES = ((WIDTH * 3 + 3) & ~3) * HEIGHT
MAX_AVI_FRAMES = (0xFFFFFFFF - 224) // (AVI_FRAME_BYTES + 24)
MAX_JOURNAL_ROW_BYTES = 16384
MIN_TIMED_SECONDS, MAX_TIMED_SECONDS = 10, 120
MIN_DIVERSE_SAMPLES, MAX_DIVERSE_SAMPLES = 5, 120
ROI_X, ROI_Y, ROI_SIZE, SIGNATURE_SIDE = 64, 24, 192, 12
DEVICE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
ID_RE = re.compile(r"[a-f0-9]{32}\Z")
UINT_RE = re.compile(r"[0-9]{1,10}\Z")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_RGB565_LUT = tuple(bytes((((v >> 11) << 3) | ((v >> 11) >> 2),
                          (((v >> 5) & 63) << 2) | (((v >> 5) & 63) >> 4),
                          ((v & 31) << 3) | ((v & 31) >> 2))) for v in range(65536))


def rgb565_to_png(data: bytes) -> bytes:
    """逐行、大端 RGB565 转无镜像 RGB888 PNG；保留原始 320×240 画面。"""
    if len(data) != FRAME_BYTES:
        raise ValueError("expected exactly 153600 bytes")
    words = array("H", data)
    if sys.byteorder == "little":
        words.byteswap()
    pixels = b"".join(b"\0" + b"".join(_RGB565_LUT[v] for v in words[y*WIDTH:(y+1)*WIDTH])
                      for y in range(HEIGHT))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels, 3)) + chunk(b"IEND", b""))


def _rgb565_to_bgr24_bottom_up(data: bytes) -> bytes:
    """将一帧大端 RGB565 转为 AVI BI_RGB 所需的倒序 BGR24。"""
    if len(data) != FRAME_BYTES:
        raise ValueError("expected exactly 153600 bytes")
    row_bytes = (WIDTH * 3 + 3) & ~3
    output = bytearray(row_bytes * HEIGHT)
    for output_y, source_y in enumerate(range(HEIGHT - 1, -1, -1)):
        source = source_y * WIDTH * 2
        target = output_y * row_bytes
        for x in range(WIDTH):
            value = data[source + x * 2] * 256 + data[source + x * 2 + 1]
            r, g, b = (value >> 11) & 31, (value >> 5) & 63, value & 31
            output[target:target + 3] = bytes(((b << 3) | (b >> 2), (g << 2) | (g >> 4),
                                                      (r << 3) | (r >> 2)))
            target += 3
    return bytes(output)


def write_rgb565_avi(target: Path, frame_paths, interval_ms: int) -> None:
    """流式写入无压缩 RGB24 AVI；无需 ffmpeg，帧顺序与采集日志一致。"""
    if not frame_paths:
        raise ValueError("AVI needs at least one frame")
    if not 200 <= interval_ms <= 5000:
        raise ValueError("interval_ms must be in [200,5000]")
    frame_size = ((WIDTH * 3 + 3) & ~3) * HEIGHT
    frame_count = len(frame_paths)
    if frame_count > MAX_AVI_FRAMES:
        raise ApiError(413, "clip_too_large", "片段超过经典 AVI 容量上限，请分段采集。")
    rate, scale = 1000, interval_ms

    def chunk(kind: bytes, payload: bytes) -> bytes:
        padding = b"\0" if len(payload) & 1 else b""
        return kind + struct.pack("<I", len(payload)) + payload + padding

    avih = struct.pack("<IIIIIIIIII4I", interval_ms * 1000,
                       math.ceil(frame_size * rate / scale), 0, 0x10, frame_count,
                       0, 1, frame_size, WIDTH, HEIGHT, 0, 0, 0, 0)
    strh = struct.pack("<4s4sIHHIIIIIIIIhhhh", b"vids", b"DIB ", 0, 0, 0, 0,
                       scale, rate, 0, frame_count, frame_size, 0xFFFFFFFF, 0,
                       0, 0, WIDTH, HEIGHT)
    strf = struct.pack("<IiiHHIIiiII", 40, WIDTH, HEIGHT, 1, 24, 0, frame_size, 0, 0, 0, 0)
    strl = chunk(b"strh", strh) + chunk(b"strf", strf)
    hdrl_payload = chunk(b"avih", avih) + b"LIST" + struct.pack("<I", 4 + len(strl)) + b"strl" + strl
    hdrl = b"LIST" + struct.pack("<I", 4 + len(hdrl_payload)) + b"hdrl" + hdrl_payload

    temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(b"RIFF\0\0\0\0AVI " + hdrl + b"LIST")
            movi_size_at = stream.tell()
            stream.write(b"\0\0\0\0movi")
            movi_type_at = movi_size_at + 4
            index = []
            for source in frame_paths:
                offset = stream.tell() - movi_type_at
                payload = _rgb565_to_bgr24_bottom_up(source.read_bytes())
                stream.write(b"00db" + struct.pack("<I", len(payload)) + payload)
                if len(payload) & 1:
                    stream.write(b"\0")
                index.append(struct.pack("<4sIII", b"00db", 0x10, offset, len(payload)))
            movi_end = stream.tell()
            idx_payload = b"".join(index)
            stream.write(b"idx1" + struct.pack("<I", len(idx_payload)) + idx_payload)
            file_end = stream.tell()
            stream.seek(movi_size_at)
            stream.write(struct.pack("<I", movi_end - movi_type_at))
            stream.seek(4)
            stream.write(struct.pack("<I", file_end - 8))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _frame_signature(data: bytes) -> tuple[int, ...]:
    """Sample a small grayscale signature from the model ROI for diversity selection."""
    if len(data) != FRAME_BYTES:
        raise ValueError("expected exactly 153600 bytes")
    step = ROI_SIZE // SIGNATURE_SIDE
    values = []
    for gy in range(SIGNATURE_SIDE):
        y = ROI_Y + gy * step + step // 2
        for gx in range(SIGNATURE_SIDE):
            x = ROI_X + gx * step + step // 2
            offset = (y * WIDTH + x) * 2
            rgb565 = (data[offset] << 8) | data[offset + 1]
            r, g, b = (rgb565 >> 11) & 31, (rgb565 >> 5) & 63, rgb565 & 31
            values.append((77 * ((r << 3) | (r >> 2))
                           + 150 * ((g << 2) | (g >> 4))
                           + 29 * ((b << 3) | (b >> 2))) >> 8)
    return tuple(values)


def select_diverse_records(record_ids, records, path_resolver, requested: int) -> list[str]:
    """Select temporally spread, visually different non-duplicate frames deterministically."""
    candidates = [key for key in record_ids if records[key].get("training_duplicate_of") is None]
    count = min(requested, len(candidates))
    if count <= 0:
        return []
    if count == len(candidates):
        return candidates
    signatures = [_frame_signature(path_resolver(records[key]["file"]).read_bytes()) for key in candidates]
    # Time anchors prevent a long clip from being represented by only one short lighting/pose interval.
    anchor_count = min(count, max(2, min(10, count // 6)))
    selected = []
    for anchor in range(anchor_count):
        index = round(anchor * (len(candidates) - 1) / max(1, anchor_count - 1))
        if index not in selected:
            selected.append(index)
    minimum = [min(sum((a - b) * (a - b) for a, b in zip(signature, signatures[old]))
                       for old in selected) for signature in signatures]
    for index in selected:
        minimum[index] = -1
    while len(selected) < count:
        # Stable tie-breaker prefers frames farther in time from the selected set.
        choice = max((index for index in range(len(candidates)) if index not in selected),
                     key=lambda index: (minimum[index], min(abs(index - old) for old in selected), -index))
        selected.append(choice)
        latest = signatures[choice]
        for index, signature in enumerate(signatures):
            if index in selected:
                minimum[index] = -1
            elif minimum[index] >= 0:
                distance = sum((a - b) * (a - b) for a, b in zip(signature, latest))
                minimum[index] = min(minimum[index], distance)
    return [candidates[index] for index in sorted(selected)]


class CaptureStore:
    """锁保护采集代际、速率、元数据和提交；磁盘目录由服务生成，不采用客户端路径。"""
    def __init__(self, root: Path, *, max_frames=10000, clock=time.monotonic):
        if not 1 <= max_frames <= 100000:
            raise ValueError("max_frames must be in [1,100000]")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_frames, self.clock = max_frames, clock
        self.lock = threading.RLock()
        self.ui_token = secrets.token_urlsafe(32)
        self.epoch = secrets.randbelow(0xFFFFFF00) + 1
        self.active = False
        self.current = None
        self.active_clip = None
        self.pending_clips = {}
        self.clips = {}
        self.interval_ms = 500
        self.sessions = {}
        self.records = {}
        self.order = []
        self.identities = {}
        self.hashes = {}
        self.pending = set()
        self.pending_preview = set()
        self.next_frame_at = {}
        self.last_error = ""
        self.last_upload_at = None
        self.last_device_id = None
        self.auto_timer = None
        self.preview_until = 0.0
        self.preview_owner = None
        self.preview_sequence = 0
        self.preview_png = None
        self.preview_metadata = {}
        self.preview_received = 0.0
        self.preview_times = []
        self._load()

    def path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate == self.root or not candidate.is_relative_to(self.root):
            raise ValueError("data path must stay inside capture root")
        return candidate

    def _load(self):
        sessions_dir = self.path("sessions")
        if not sessions_dir.exists():
            return
        clip_members = {}
        for folder in sorted(sessions_dir.iterdir()):
            if not folder.is_dir() or not ID_RE.fullmatch(folder.name):
                continue
            metadata = self.path(f"sessions/{folder.name}/session.json")
            if metadata.stat().st_size > 16384:
                raise ValueError(f"oversized session metadata: {metadata}")
            session = json.loads(metadata.read_text(encoding="utf-8"))
            if session.get("session_id") != folder.name or session.get("split") not in SPLITS:
                raise ValueError(f"invalid session metadata: {metadata}")
            self.sessions[folder.name] = session
            journal = self.path(f"sessions/{folder.name}/frames.jsonl")
            if not journal.exists():
                continue
            with journal.open("rb") as stream:
                for number, line in enumerate(stream, 1):
                    if len(line) > 16384:
                        raise ValueError(f"oversized journal row: {journal}:{number}")
                    event = json.loads(line)
                    if event.get("type") == "frame":
                        row = event["sample"]
                        record_id = row["record_id"]
                        if (not ID_RE.fullmatch(record_id) or record_id in self.records
                                or row.get("session") != folder.name or row.get("split") != session["split"]
                                or row.get("label") not in LABELS + (PENDING_LABEL,)):
                            raise ValueError(f"invalid or duplicate journal sample: {journal}:{number}")
                        for suffix, field in (("rgb565", "file"), ("png", "preview_file")):
                            expected = f"sessions/{folder.name}/frames/{record_id}.{suffix}"
                            if row.get(field) != expected or not self.path(expected).is_file():
                                raise ValueError(f"missing/invalid captured file: {journal}:{number}")
                        if len(self.records) >= self.max_frames:
                            raise ValueError("existing data exceeds --max-frames; increase that explicit limit")
                        identity = (folder.name, row["device_id"], row["frame_id"])
                        if identity in self.identities:
                            raise ValueError(f"duplicate frame identity/content: {journal}:{number}")
                        duplicate_of = row.get("training_duplicate_of")
                        # UUID directory order is unrelated to capture chronology.
                        # Validate cross-session references after every frame is loaded.
                        if duplicate_of is None and row["sha256"] in self.hashes:
                            raise ValueError(f"duplicate content without reference: {journal}:{number}")
                        self.records[record_id] = row
                        self.order.append(record_id)
                        if row.get("clip_id"):
                            clip_members.setdefault(row["clip_id"], []).append(record_id)
                        self.identities[identity] = record_id
                        if duplicate_of is None:
                            self.hashes[row["sha256"]] = record_id
                    elif event.get("type") == "annotation":
                        record_id = event["record_id"]
                        if (record_id not in self.records or self.records[record_id]["session"] != folder.name
                                or event.get("label") not in LABELS or type(event.get("excluded")) is not bool):
                            raise ValueError(f"invalid annotation: {journal}:{number}")
                        self.records[record_id].update(label=event["label"], excluded=event["excluded"],
                                                       annotation_updated_at=event["at"])
                    elif event.get("type") == "clip":
                        clip_id = event.get("clip_id")
                        record_ids = event.get("record_ids")
                        if event.get("membership") == "frame_journal":
                            record_ids = list(clip_members.get(clip_id, []))
                            if (type(event.get("record_count")) is not int
                                    or event["record_count"] != len(record_ids)):
                                raise ValueError(f"invalid clip member count: {journal}:{number}")
                            event["record_ids"] = record_ids
                        if (not isinstance(clip_id, str) or not ID_RE.fullmatch(clip_id)
                                or clip_id in self.clips or not isinstance(record_ids, list)
                                or not record_ids or any(key not in self.records for key in record_ids)
                                or record_ids != clip_members.get(clip_id, [])
                                or event.get("session") != folder.name
                                or any(self.records[key].get("clip_id") != clip_id for key in record_ids)
                                or event.get("status") not in ("labeled", "discarded")):
                            raise ValueError(f"invalid clip journal row: {journal}:{number}")
                        if event["status"] == "labeled":
                            if event.get("label") not in LABELS:
                                raise ValueError(f"invalid clip label: {journal}:{number}")
                            video_file = event.get("video_file")
                            expected_prefix = f"sessions/{folder.name}/clips/"
                            if (not isinstance(video_file, str) or not video_file.startswith(expected_prefix)
                                    or not video_file.endswith(".avi") or not self.path(video_file).is_file()):
                                raise ValueError(f"missing/invalid clip video: {journal}:{number}")
                            selected_ids = event.get("selected_record_ids")
                            if selected_ids is not None:
                                if (not isinstance(selected_ids, list) or len(selected_ids) != len(set(selected_ids))
                                        or any(key not in record_ids for key in selected_ids)):
                                    raise ValueError(f"invalid diverse selection: {journal}:{number}")
                                selected_ids = set(selected_ids)
                            for key in record_ids:
                                row = self.records[key]
                                row.update(label=event["label"], video_file=video_file,
                                           label_provenance=event.get("label_provenance", "manual_post_clip_label"),
                                           clip_labeled_at=event["completed_at"])
                                row["excluded"] = (event.get('capture_only', False) or row.get("training_duplicate_of") is not None
                                                   or (selected_ids is not None and key not in selected_ids))
                                if selected_ids is not None:
                                    row["diversity_selected"] = key in selected_ids
                        else:
                            for key in record_ids:
                                self.records[key].update(excluded=True, clip_discarded_at=event["completed_at"])
                        self.clips[clip_id] = event
                    else:
                        raise ValueError(f"unknown journal row: {journal}:{number}")
        for row in self.records.values():
            duplicate_of = row.get("training_duplicate_of")
            if duplicate_of is not None:
                original = self.records.get(duplicate_of)
                if (original is None or original.get("training_duplicate_of") is not None
                        or original["sha256"] != row["sha256"] or duplicate_of == row["record_id"]):
                    raise ValueError(f"invalid duplicate reference: {row['record_id']}")
                # Older versions allowed manual re-inclusion. Keep their video/label, but
                # recover the training invariant without rewriting historical journals.
                row["excluded"] = True
        self.order.sort(key=lambda key: self.records[key]["received_at"])
        pending = {}
        for key in self.order:
            row = self.records[key]
            clip_id = row.get("clip_id")
            if row.get("label") == PENDING_LABEL and clip_id not in self.clips:
                clip = pending.setdefault(clip_id, dict(clip_id=clip_id, session_id=row["session"],
                                                       interval_ms=row.get("clip_interval_ms", 500),
                                                       started_at=row.get("clip_started_at", row["received_at"]),
                                                       stopped_at=row["received_at"], record_ids=[]))
                clip["record_ids"].append(key)
                clip["stopped_at"] = row["received_at"]
        self.pending_clips = pending

    def _bump(self):
        self.epoch = (self.epoch + 1) & 0xFFFFFFFF
        # A new recording/session must not inherit an old observation image.
        self.preview_png = None
        self.preview_metadata = {}
        self.preview_times = []

    def _journal(self, session_id, event):
        if event.get("type") == "clip":
            # Membership already lives in the ordered frame events. Avoid an unbounded JSONL row.
            event = dict(event, membership="frame_journal", record_count=len(event["record_ids"]))
            del event["record_ids"]
        payload = json_bytes(event)
        if len(payload) > MAX_JOURNAL_ROW_BYTES:
            raise ValueError("journal event exceeds bounded row size")
        with self.path(f"sessions/{session_id}/frames.jsonl").open("ab") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def state(self):
        with self.lock:
            counts = Counter(row["label"] for row in self.records.values()
                             if row["label"] in LABELS and not row.get("excluded", False))
            recent = [dict(self.records[key]) for key in reversed(self.order[-30:])]
            pending = [self._clip_summary(clip) for clip in self.pending_clips.values()]
            recent_clips = [self._clip_summary(clip) for clip in
                            sorted(self.clips.values(), key=lambda item: item["completed_at"], reverse=True)[:12]]
            return dict(active=self.active, epoch=self.epoch, interval_ms=self.interval_ms,
                        session=self.current, active_clip=self._clip_summary(self.active_clip),
                        pending_clips=pending, recent_clips=recent_clips, labels=LABELS,
                        label_names=LABEL_NAMES, splits=SPLITS,
                        total=len(self.records), included=sum(counts.values()), counts=counts,
                        recent=recent, last_error=self.last_error, ui_token=self.ui_token,
                        last_upload_at=self.last_upload_at, last_device_id=self.last_device_id,
                        output_root=str(self.root), max_frames=self.max_frames,
                        capabilities=["live_preview_v1"], preview=self.preview_status())

    def preview_status(self):
        with self.lock:
            now = self.clock()
            times = [stamp for stamp in self.preview_times if now - stamp < 4]
            fps = ((len(times) - 1) / (times[-1] - times[0])
                   if len(times) > 1 and times[-1] > times[0] else 0.0)
            return dict(enabled=now < self.preview_until, sequence=self.preview_sequence,
                        age_ms=round((now-self.preview_received)*1000) if self.preview_png else None,
                        received_fps=round(fps, 2), **self.preview_metadata)

    def preview_action(self, data):
        owner, action = data.get("owner"), data.get("action")
        if not isinstance(owner, str) or not ID_RE.fullmatch(owner) or action not in ("start", "keep", "stop"):
            raise ApiError(400, "preview_request", "无效观察请求。")
        with self.lock:
            alive = self.clock() < self.preview_until
            if alive and self.preview_owner != owner:
                raise ApiError(409, "preview_owned", "另一窗口正在观察，请先在原窗口停止观察。")
            if action == "stop":
                self.preview_until = 0
                self.preview_owner = None
                if not self.active:
                    self._bump()
            else:
                if action == "keep" and (not alive or self.preview_owner != owner):
                    raise ApiError(409, "preview_expired", "观察已过期，请重新开始观察。")
                self.preview_owner = owner
                self.preview_until = self.clock() + 15
                if not alive and not self.active:
                    self._bump()
            return self.preview_status()

    def _publish_preview(self, ticket, png):
        # Called while holding the store lock. One encoded latest frame, no queue.
        now = self.clock()
        self.preview_sequence += 1
        self.preview_png, self.preview_received = png, now
        self.preview_metadata = dict(frame_id=ticket["frame_id"], device_id=ticket["device_id"],
                                     received_at=utc_now())
        self.preview_times = [t for t in self.preview_times if now-t < 4][-39:] + [now]

    @staticmethod
    def _clip_summary(clip):
        if clip is None:
            return None
        result = {key: clip.get(key) for key in ("clip_id", "session_id", "status", "label",
                                                  "video_file", "display_name", "interval_ms",
                                                  "started_at", "stopped_at", "completed_at",
                                                  "duration_seconds", "auto_stop_at", "selection_method",
                                                  "selection_requested", "processing", "processing_error", "capture_only") if key in clip}
        result["frame_count"] = len(clip.get("record_ids", []))
        if "selected_record_ids" in clip:
            result["selected_count"] = len(clip["selected_record_ids"])
        return result

    def _cancel_auto_timer(self):
        timer, self.auto_timer = self.auto_timer, None
        if timer is not None:
            timer.cancel()

    def _complete_stopped_clip(self, clip_id):
        """Finish outside the request lock so in-flight uploads can release."""
        try:
            deadline = time.monotonic() + 10
            while self.pending_recordings and time.monotonic() < deadline:
                time.sleep(0.02)
            with self.lock:
                clip = self.pending_clips.get(clip_id)
                if clip is None:  # Explicit new/close already discarded staging.
                    return
                clip['processing'] = False
                self.clip_action({'action': 'label', 'clip_id': clip_id})
        except Exception as error:
            with self.lock:
                clip = self.pending_clips.get(clip_id)
                if clip is not None:
                    clip['processing'] = False
                    clip['processing_error'] = str(error)
                    self.last_error = f"录制已停止，自动整理失败：{error}。请重试确认标签或放弃片段。"

    def _queue_stopped_clip(self, clip_id):
        clip = self.pending_clips[clip_id]
        clip['processing'] = True
        clip.pop('processing_error', None)
        threading.Thread(target=self._complete_stopped_clip, args=(clip_id,),
                         name='clip-finalize', daemon=True).start()

    def _finish_timed_clip(self, clip_id):
        with self.lock:
            if self.active_clip is None or self.active_clip['clip_id'] != clip_id:
                return
            self.clip_action({'action': 'stop'})
            self.pending_clips[clip_id]['processing'] = True
        # The timer already runs off the HTTP thread. Keep its completion
        # synchronous to the callback, using the same finalizer as early finish.
        self._complete_stopped_clip(clip_id)

    def control(self):
        with self.lock:
            enabled = int(self.active and len(self.records) < self.max_frames
                          and self.active_clip is not None
                          and len(self.active_clip["record_ids"]) < MAX_AVI_FRAMES)
            observing = not self.active and self.clock() < self.preview_until
            return f"enabled={int(enabled or observing)}\ninterval_ms={200 if observing else self.interval_ms}\nepoch={self.epoch}\n".encode("ascii")

    def page(self, offset, limit):
        if not 0 <= offset <= 100000 or not 1 <= limit <= 60:
            raise ApiError(400, "page_range", "offset 须为 0–100000；limit 须为 1–60。")
        with self.lock:
            end = max(0, len(self.order) - offset)
            keys = reversed(self.order[max(0, end - limit):end])
            return dict(total=len(self.order), offset=offset, samples=[dict(self.records[key]) for key in keys])

    def session_action(self, data):
        with self.lock:
            action = data.get("action")
            if action == "new":
                if self.current is not None:
                    raise ApiError(409, "session_open", "请先结束当前会话。")
                if self.pending_clips:
                    raise ApiError(409, "clip_needs_label", "请先给上一段视频选择手势或放弃该片段。")
                split = data.get("split")
                if split not in SPLITS:
                    raise ApiError(400, "invalid_split", "请选择合法的会话用途。")
                values = {}
                for field in ("name", "sensor_profile", "exposure_profile"):
                    value = data.get(field, "")
                    if not isinstance(value, str) or not value.strip() or len(value) > 160 or any(ord(c) < 32 for c in value):
                        raise ApiError(400, "session_metadata", f"{field} 必须是 1–160 字符的文本。")
                    values[field] = value.strip()
                session_id = uuid.uuid4().hex
                session = dict(session_id=session_id, split=split, created_at=utc_now(), **values)
                self.path(f"sessions/{session_id}/frames").mkdir(parents=True, exist_ok=False)
                self.path(f"sessions/{session_id}/clips").mkdir(parents=True, exist_ok=False)
                atomic_json(self.path(f"sessions/{session_id}/session.json"), session)
                self.sessions[session_id] = session
                self.current = session
                self.active = False
                self._bump()
            elif action == "stop":
                if self.current is None:
                    raise ApiError(409, "no_session", "请先新建会话。")
                if self.active_clip is not None or self.pending_clips or self.pending_recordings:
                    raise ApiError(409, "clip_open", "请先停止当前片段并完成采后标注。")
                closed = dict(self.current, ended_at=utc_now())
                atomic_json(self.path(f"sessions/{closed['session_id']}/session.json"), closed)
                self.sessions[closed["session_id"]] = closed
                self.current = None
                self._bump()
            else:
                raise ApiError(400, "invalid_action", "未知会话操作。")
            return self.state()

    def clip_action(self, data):
        with self.lock:
            action = data.get("action")
            if action == "start":
                if self.current is None:
                    raise ApiError(409, "no_session", "请先新建会话。")
                if self.active_clip is not None or self.pending_clips:
                    raise ApiError(409, "clip_open", "请先停止并标注上一段视频。")
                fps = data.get("fps", 5)
                if type(fps) not in (int, float) or not math.isfinite(fps) or not 0.2 <= fps <= 5:
                    raise ApiError(400, "invalid_rate", "视频采样率须为 0.2–5 帧/秒。")
                label = data.get("label")
                duration = data.get("duration_seconds")
                capture_only = getattr(self, 'raw_capture_only', False)
                selection = None if capture_only else data.get("selection_count")
                timed = label is not None or duration is not None or selection is not None
                if timed:
                    if label not in LABELS:
                        raise ApiError(400, "invalid_label", "请选择本段视频对应的手势类别。")
                    if type(duration) not in (int, float) or not math.isfinite(duration) or not MIN_TIMED_SECONDS <= duration <= MAX_TIMED_SECONDS:
                        raise ApiError(400, "invalid_duration", f"自动录制时长须为 {MIN_TIMED_SECONDS}–{MAX_TIMED_SECONDS} 秒。")
                    if not capture_only and (type(selection) is not int or not MIN_DIVERSE_SAMPLES <= selection <= MAX_DIVERSE_SAMPLES):
                        raise ApiError(400, "invalid_selection", f"代表帧数量须为 {MIN_DIVERSE_SAMPLES}–{MAX_DIVERSE_SAMPLES}。")
                if len(self.records) >= self.max_frames:
                    raise ApiError(409, "frame_limit", "已达到保存上限，请换输出目录或显式增加上限。")
                self.interval_ms = math.ceil(1000 / fps)
                clip_id = uuid.uuid4().hex
                self.active_clip = dict(clip_id=clip_id, session_id=self.current["session_id"],
                                        interval_ms=self.interval_ms, started_at=utc_now(), record_ids=[])
                if timed:
                    self.active_clip.update(label=label, duration_seconds=duration,
                                            selection_requested=selection,
                                            selection_method="roi-gray12-temporal-farthest-v1",
                                            auto_stop_at=(datetime.now(timezone.utc)
                                                          + timedelta(seconds=duration)).isoformat(timespec="milliseconds"))
                if capture_only:
                    self.active_clip['capture_only'] = True
                    self.active_clip.pop('selection_requested', None)
                    self.active_clip.pop('selection_method', None)
                self.active = True
                self._bump()
                if duration is not None:
                    self._cancel_auto_timer()
                    self.auto_timer = threading.Timer(duration, self._finish_timed_clip, args=(clip_id,))
                    self.auto_timer.daemon = True
                    self.auto_timer.start()
            elif action in ("stop", "finish"):
                if self.active_clip is None:
                    raise ApiError(409, "no_active_clip", "当前没有正在录制的视频片段。")
                self.active = False
                clip = dict(self.active_clip, stopped_at=utc_now())
                self.active_clip = None
                self.pending_clips[clip["clip_id"]] = clip
                self._cancel_auto_timer()
                self._bump()
                if action == "finish" and clip.get('label') in LABELS:
                    self._queue_stopped_clip(clip['clip_id'])
            elif action in ("label", "discard"):
                clip_id = data.get("clip_id")
                if not isinstance(clip_id, str) or clip_id not in self.pending_clips:
                    raise ApiError(404, "unknown_clip", "找不到待标注的视频片段。")
                if self.active or self.pending_recordings:
                    raise ApiError(409, "upload_in_progress", "请等待在途帧结束后再保存片段标注。")
                clip = self.pending_clips[clip_id]
                if clip.get('processing'):
                    raise ApiError(409, 'clip_processing', '正在整理片段，请稍候。')
                record_ids = list(clip["record_ids"])
                if not record_ids:
                    if action == "label":
                        raise ApiError(409, "empty_clip", "该片段没有收到完整帧，请放弃后重新录制。")
                    del self.pending_clips[clip_id]
                    return self.state()
                completed_at = utc_now()
                if action == "discard":
                    event = dict(type="clip", status="discarded", clip_id=clip_id,
                                 session=clip["session_id"], record_ids=record_ids,
                                 started_at=clip["started_at"], stopped_at=clip["stopped_at"],
                                 interval_ms=clip["interval_ms"], completed_at=completed_at)
                    self._journal(clip["session_id"], event)
                    for key in record_ids:
                        self.records[key].update(excluded=True, clip_discarded_at=completed_at)
                else:
                    label = data.get("label", clip.get("label"))
                    if label not in LABELS:
                        raise ApiError(400, "invalid_label", "请选择这段视频对应的七类手势。")
                    session_prefix = f"sessions/{clip['session_id']}/clips"
                    clip_dir = self.path(session_prefix)
                    clip_dir.mkdir(parents=True, exist_ok=True)
                    stem = f"{label}_{LABEL_NAMES[label]}"
                    sequence = 1
                    while self.path(f"{session_prefix}/{stem}_{sequence:04d}.avi").exists():
                        sequence += 1
                    video_file = f"{session_prefix}/{stem}_{sequence:04d}.avi"
                    video_path = self.path(video_file)
                    write_rgb565_avi(video_path, [self.path(self.records[key]["file"]) for key in record_ids],
                                     clip["interval_ms"])
                    selected_ids = None
                    if "selection_requested" in clip and not clip.get('capture_only'):
                        selected_ids = select_diverse_records(record_ids, self.records, self.path,
                                                              clip["selection_requested"])
                        if not selected_ids:
                            video_path.unlink(missing_ok=True)
                            raise ApiError(409, "no_unique_frames", "片段没有可用于训练的非重复帧，请重新录制。")
                    event = dict(type="clip", status="labeled", clip_id=clip_id,
                                 session=clip["session_id"], label=label,
                                 display_name=LABEL_NAMES[label], video_file=video_file,
                                 record_ids=record_ids, started_at=clip["started_at"],
                                 stopped_at=clip["stopped_at"], interval_ms=clip["interval_ms"],
                                 completed_at=completed_at)
                    if clip.get('capture_only'):
                        event.update(capture_only=True, label_provenance='manual_recording_intent_unreviewed')
                    if selected_ids is not None:
                        event.update(selected_record_ids=selected_ids,
                                     selection_requested=clip["selection_requested"],
                                     selection_method=clip["selection_method"],
                                     duration_seconds=clip["duration_seconds"],
                                     label_provenance="manual_pre_clip_label_diversity_selected")
                    try:
                        self._journal(clip["session_id"], event)
                    except OSError:
                        video_path.unlink(missing_ok=True)
                        raise
                    selected_set = set(selected_ids) if selected_ids is not None else None
                    for key in record_ids:
                        row = self.records[key]
                        row.update(label=label, video_file=video_file,
                                   label_provenance=event.get("label_provenance", "manual_post_clip_label"),
                                   clip_labeled_at=completed_at)
                        row["excluded"] = (event.get('capture_only', False) or row.get("training_duplicate_of") is not None
                                           or (selected_set is not None and key not in selected_set))
                        if selected_set is not None:
                            row["diversity_selected"] = key in selected_set
                self.clips[clip_id] = event
                del self.pending_clips[clip_id]
                self._bump()
            else:
                raise ApiError(400, "invalid_action", "未知视频片段操作。")
            return self.state()

    @property
    def pending_recordings(self):
        return self.pending - self.pending_preview

    def begin(self, metadata):
        with self.lock:
            if not self.active and self.clock() < self.preview_until and metadata["epoch"] == self.epoch:
                device = metadata["device_id"]
                if device in self.pending:
                    raise ApiError(429, "upload_in_progress", "同一设备已有上传在途。")
                self.pending.add(device)
                self.pending_preview.add(device)
                return dict(metadata, preview_only=True)
            if (not self.active or self.current is None or self.active_clip is None
                    or metadata["epoch"] != self.epoch):
                raise ApiError(409, "control_changed", "采集已暂停或控制版本已变化，请重新读取 control。")
            if len(self.records) >= self.max_frames:
                raise ApiError(409, "frame_limit", "已达到保存上限。")
            device = metadata["device_id"]
            identity = (self.current["session_id"], device, metadata["frame_id"])
            if identity not in self.identities and len(self.active_clip["record_ids"]) >= MAX_AVI_FRAMES:
                raise ApiError(409, "clip_limit", "片段达到 AVI 上限，请停止并标注后再录新片段。")
            if device in self.pending:
                raise ApiError(429, "upload_in_progress", "同一设备已有上传在途。")
            # 已提交帧的重试不受采样周期影响，但仍校验完整正文及代际。
            if identity not in self.identities and self.clock() < self.next_frame_at.get(device, 0):
                raise ApiError(429, "rate_limited", "上传间隔过短，请遵守 interval_ms。")
            self.pending.add(device)
            return dict(session=dict(self.current), clip=dict(self.active_clip), epoch=self.epoch,
                        identity=identity, **{k: v for k, v in metadata.items() if k != "epoch"})

    def release(self, ticket):
        with self.lock:
            self.pending.discard(ticket["device_id"])
            self.pending_preview.discard(ticket["device_id"])

    def commit(self, ticket, raw):
        digest = hashlib.sha256(raw).hexdigest()
        png = rgb565_to_png(raw)
        with self.lock:
            if ticket.get("preview_only"):
                if self.active or self.clock() >= self.preview_until or ticket["epoch"] != self.epoch:
                    raise ApiError(409, "control_changed", "观察已停止或已切换录制。")
                self._publish_preview(ticket, png)
                return 200, dict(ok=True, preview_only=True)
            if (not self.active or self.current is None or self.active_clip is None
                    or ticket["epoch"] != self.epoch
                    or ticket["session"]["session_id"] != self.current["session_id"]
                    or ticket["clip"]["clip_id"] != self.active_clip["clip_id"]):
                raise ApiError(409, "control_changed", "在途帧跨越了片段停止或会话变化，已丢弃。")
            old = self.identities.get(ticket["identity"])
            if old:
                if self.records[old]["sha256"] != digest:
                    raise ApiError(409, "frame_id_reused", "同会话设备 frame_id 已用于另一图像，请保持单调或新建会话。")
                self.last_upload_at, self.last_device_id = utc_now(), ticket["device_id"]
                return 200, dict(ok=True, duplicate=True, record_id=old)
            if len(self.records) >= self.max_frames:
                raise ApiError(409, "frame_limit", "已达到保存上限。")
            if len(self.active_clip["record_ids"]) >= MAX_AVI_FRAMES:
                raise ApiError(409, "clip_limit", "片段达到 AVI 上限，请停止并标注后再录新片段。")
            record_id = uuid.uuid4().hex
            session = ticket["session"]
            clip = ticket["clip"]
            prefix = f"sessions/{session['session_id']}/frames/{record_id}"
            row = dict(record_id=record_id, file=prefix + ".rgb565", preview_file=prefix + ".png",
                       sha256=digest, session=session["session_id"], session_id=session["session_id"],
                       label=PENDING_LABEL, split=session["split"], sensor_profile=session["sensor_profile"],
                       exposure_profile=session["exposure_profile"], capture_ms=ticket["capture_ms"],
                       width=WIDTH, height=HEIGHT, stride_bytes=WIDTH * 2, byte_order="msb_first",
                       pixel_format="RGB565_BE", device_id=ticket["device_id"], frame_id=ticket["frame_id"],
                       annotation_epoch=ticket["epoch"], received_at=utc_now(), excluded=True,
                       source="personal_board_capture", label_provenance="pending_post_clip_label",
                       clip_id=clip["clip_id"], clip_started_at=clip["started_at"],
                       clip_interval_ms=clip["interval_ms"])
            duplicate_of = self.hashes.get(digest)
            if duplicate_of is not None:
                row["training_duplicate_of"] = duplicate_of
            created = []
            try:
                for relative, content in ((row["file"], raw), (row["preview_file"], png)):
                    path = self.path(relative)
                    with path.open("xb") as stream:
                        created.append(path)
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                self._journal(session["session_id"], dict(type="frame", sample=row))
            except OSError:
                # 只回滚本次新建文件，不删除历史数据；磁盘错误后暂停，避免继续堆积。
                self.active = False
                self._bump()
                self.last_error = "保存失败，采集已暂停。请检查磁盘空间、权限及会话日志。"
                for path in created:
                    path.unlink(missing_ok=True)
                raise
            self.records[record_id] = row
            self.order.append(record_id)
            self.identities[ticket["identity"]] = record_id
            if duplicate_of is None:
                self.hashes[digest] = record_id
            self.active_clip["record_ids"].append(record_id)
            self.next_frame_at[ticket["device_id"]] = self.clock() + self.interval_ms / 1000
            self.last_upload_at, self.last_device_id = utc_now(), ticket["device_id"]
            self._publish_preview(ticket, png)
            return 201, dict(ok=True, duplicate=False, record_id=record_id, sha256=digest)

    def annotate(self, data):
        with self.lock:
            if self.active or self.pending_recordings:
                raise ApiError(409, "capture_active", "请暂停采集并等在途上传结束，再修改历史标注。")
            record_id = data.get("record_id")
            if not isinstance(record_id, str) or record_id not in self.records:
                raise ApiError(404, "unknown_frame", "找不到该帧。")
            label, excluded = data.get("label"), data.get("excluded")
            if label not in LABELS or type(excluded) is not bool:
                raise ApiError(400, "invalid_annotation", "需要合法标签和布尔 excluded。")
            row = self.records[record_id]
            if row["label"] == PENDING_LABEL:
                raise ApiError(409, "clip_needs_label", "请先给整段视频选择手势，再逐帧修正。")
            if row.get("training_duplicate_of") is not None and not excluded:
                raise ApiError(409, "training_duplicate", "重复原始帧保留在视频中，但不可重新加入训练清单。")
            event = dict(type="annotation", record_id=record_id, label=label, excluded=excluded, at=utc_now())
            self._journal(row["session"], event)
            row.update(label=label, excluded=excluded, annotation_updated_at=event["at"])
            return dict(ok=True, sample=dict(row))

    def export(self):
        with self.lock:
            if self.active or self.pending_recordings or self.pending_clips:
                raise ApiError(409, "capture_active", "请停止片段、完成采后标注并等在途上传结束。")
            rows = [dict(self.records[key]) for key in self.order
                    if self.records[key]["label"] in LABELS and not self.records[key].get("excluded", False)
                    and self.records[key].get("training_duplicate_of") is None]
            clip_fields = ("clip_id", "session", "label", "display_name", "video_file", "record_ids",
                           "started_at", "stopped_at", "interval_ms", "completed_at", "selected_record_ids",
                           "selection_requested", "selection_method", "duration_seconds")
            clips = [{key: clip[key] for key in clip_fields if key in clip}
                     for clip in sorted(self.clips.values(), key=lambda item: item["completed_at"])
                     if clip["status"] == "labeled"]
            manifest = dict(schema_version=1, preprocessing=PREPROCESSING,
                            note="手势视频停止后人工选标签；训练仍读取逐帧 samples，clips 保留视频级追溯。split 以整会话固定。",
                            exported_at=utc_now(), samples=rows, clips=clips)
            target = self.path("dataset_manifest.json")
            atomic_json(target, manifest)
            return dict(ok=True, sample_count=len(rows), manifest=str(target), download="/api/export")


class CaptureHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, address, store, *, read_timeout=5.0, usb_receiver=None):
        self.store, self.read_timeout = store, read_timeout
        self.usb_receiver = usb_receiver
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, CaptureHandler)

    def state(self):
        # Finish the store snapshot before taking the receiver's diagnostic
        # lock. USB acceptance takes store locks too; never nest the two.
        result = self.store.state()
        if self.usb_receiver is not None:
            result["usb"] = self.usb_receiver.snapshot()
        return result

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(0.2)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class CaptureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "GestureCapture/1"

    def setup(self):
        self._received_body_bytes = 0
        self.request.settimeout(self.server.read_timeout)
        super().setup()

    def log_message(self, fmt, *args):
        # 不输出不可信的请求内容或每帧刷屏；错误在结构化 HTTP 返回中显示。
        pass

    def send_content(self, status, content, kind="application/json; charset=utf-8", *, attachment=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(content)
        if status >= 400:
            self._finish_rejection()

    def _finish_rejection(self):
        """Send the error before a bounded drain, avoiding unread-body TCP resets.

        A Windows close with pending request bytes may discard the 429/409
        response. Half-close the output first, then consume at most one frame
        for at most 0.5s. This never reserves a device or saves rejected data.
        """
        self.wfile.flush()
        self.connection.shutdown(socket.SHUT_WR)
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0].strip()):
            return
        remaining = min(FRAME_BYTES, max(0, int(lengths[0])-self._received_body_bytes))
        deadline = time.monotonic() + 0.5
        try:
            while remaining:
                budget = deadline-time.monotonic()
                if budget <= 0:
                    break
                self.connection.settimeout(budget)
                part = self.rfile.read1(min(65536, remaining))
                if not part:
                    break
                remaining -= len(part)
        except OSError:
            pass

    def send_path(self, path: Path, kind: str):
        """流式发送可能较大的视频文件，避免一次读入内存。"""
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(size))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as stream:
            while True:
                block = stream.read(262144)
                if not block:
                    break
                self.wfile.write(block)

    def _one_header(self, name, required=True):
        values = self.headers.get_all(name, [])
        if len(values) != 1:
            if not values and not required:
                return None
            raise ApiError(400, "invalid_header", f"需要唯一的 {name} 请求头。")
        return values[0].strip()

    def _site_check(self):
        host = self._one_header("Host", required=False)
        if host:
            try:
                hostname = urlsplit("http://" + host).hostname
                if hostname != "localhost":
                    ipaddress.ip_address(hostname)
            except (ValueError, TypeError):
                raise ApiError(403, "host_rejected", "请通过 localhost 或电脑 IP 访问。")
        origin = self._one_header("Origin", required=False)
        if origin and (not host or origin != "http://" + host):
            raise ApiError(403, "origin_rejected", "不接受其他网页来源的请求。")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ApiError(403, "cross_site", "不接受跨站请求。")

    def _body(self, maximum, exact=None):
        if self.headers.get_all("Transfer-Encoding"):
            raise ApiError(400, "transfer_encoding", "不支持分块传输；请提供 Content-Length。")
        text = self._one_header("Content-Length")
        if not re.fullmatch(r"[0-9]{1,10}", text):
            raise ApiError(400, "content_length", "无效 Content-Length。")
        length = int(text)
        if length > maximum:
            raise ApiError(413, "body_too_large", "请求正文超过上限。")
        if exact is not None and length != exact:
            raise ApiError(400, "frame_length", f"完整帧必须是 {exact} 字节。")
        deadline = time.monotonic() + self.server.read_timeout
        chunks, remaining = [], length
        while remaining:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise ApiError(408, "body_timeout", "上传超时，未保存任何帧。")
            self.connection.settimeout(budget)
            try:
                part = self.rfile.read1(min(65536, remaining))
            except (TimeoutError, socket.timeout):
                raise ApiError(408, "body_timeout", "上传超时，未保存任何帧。")
            if not part:
                raise ApiError(400, "truncated_body", "连接中断或正文不完整，未保存任何帧。")
            chunks.append(part)
            self._received_body_bytes += len(part)
            remaining -= len(part)
        return b"".join(chunks)

    def _json_body(self):
        if self._one_header("X-UI-Token", required=False) != self.server.store.ui_token:
            raise ApiError(403, "ui_token", "请从本服务的采集网页操作。")
        if self._one_header("Content-Type").split(";")[0].strip().lower() != "application/json":
            raise ApiError(415, "content_type", "界面请求必须是 application/json。")
        try:
            value = json.loads(self._body(4096))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "json", "无效 JSON。")
        if not isinstance(value, dict):
            raise ApiError(400, "json_object", "JSON 必须是对象。")
        return value

    def _frame(self):
        if self._one_header("Content-Type").split(";")[0].strip().lower() != "application/octet-stream":
            raise ApiError(415, "content_type", "帧必须为 application/octet-stream。")
        if (self._one_header("X-Width") != "320" or self._one_header("X-Height") != "240"
                or self._one_header("X-Pixel-Format") != "RGB565_BE"):
            raise ApiError(415, "pixel_format", "只接受连续 320×240 RGB565_BE。")
        device_id = self._one_header("X-Device-ID")
        if not DEVICE_RE.fullmatch(device_id):
            raise ApiError(400, "device_id", "设备 ID 仅允许 1–64 位字母、数字、下划线或连字符。")
        metadata = dict(device_id=device_id)
        for header, field in (("X-Frame-ID", "frame_id"), ("X-Capture-Ms", "capture_ms"), ("X-Control-Epoch", "epoch")):
            value = self._one_header(header)
            if not UINT_RE.fullmatch(value) or int(value) > 0xFFFFFFFF:
                raise ApiError(400, "integer_header", f"{header} 必须是 uint32 十进制。")
            metadata[field] = int(value)
        # 先校验长度再占用设备，在读正文前固定标签/会话/代际。
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0].strip()):
            raise ApiError(400, "content_length", "需要唯一合法的 Content-Length。")
        if int(lengths[0]) != FRAME_BYTES:
            raise ApiError(413 if int(lengths[0]) > FRAME_BYTES else 400, "frame_length", "完整帧必须是 153600 字节。")
        ticket = self.server.store.begin(metadata)
        try:
            raw = self._body(FRAME_BYTES, exact=FRAME_BYTES)
            status, result = self.server.store.commit(ticket, raw)
            self.send_content(status, json_bytes(result))
        finally:
            self.server.store.release(ticket)

    def _dispatch(self):
        self._site_check()
        path = urlsplit(self.path).path
        store = self.server.store
        if self.command == "POST":
            if path == "/api/frames":
                return self._frame()
            data = self._json_body()
            if hasattr(store, 'require_owner') and path in ('/api/session', '/api/clip', '/api/annotate', '/api/export'):
                # Ownership check and mutation share one critical section.
                with store.lock:
                    store.require_owner(data)
                    actions = {'/api/session': store.session_action, '/api/clip': store.clip_action,
                               '/api/annotate': store.annotate, '/api/export': lambda d:store.export(d.get('scope', 'current'))}
                    result = actions[path](data)
                return self.send_content(200, json_bytes(result))
            if path == "/api/session":
                result = store.session_action(data)
            elif path == "/api/clip":
                result = store.clip_action(data)
            elif path == "/api/annotate":
                result = store.annotate(data)
            elif path == "/api/export":
                result = store.export()
            elif path == "/api/preview":
                result = store.preview_action(data)
            elif path == "/api/workspace" and hasattr(store, 'workspace_action'):
                result = store.workspace_action(data)
            else:
                raise ApiError(404, "not_found", "找不到接口。")
            return self.send_content(200, json_bytes(result))
        if self.command != "GET":
            raise ApiError(405, "method", "仅支持 GET 和 POST。")
        if path == "/api/control":
            return self.send_content(200, store.control(), "text/plain; charset=ascii")
        if path == "/api/state":
            return self.send_content(200, json_bytes(self.server.state()))
        if path == '/api/live' and hasattr(store, 'live'):
            return self.send_content(200, json_bytes(store.live()))
        if path == '/api/history' and hasattr(store, 'history'):
            return self.send_content(200, json_bytes(store.history()))
        if path == "/api/preview.png":
            query = parse_qs(urlsplit(self.path).query)
            after = query.get("after", ["0"])[0]
            if not after.isdecimal() or len(after) > 20:
                raise ApiError(400, "preview_sequence", "无效帧序号。")
            with store.lock:
                status = store.preview_status()
                png = store.preview_png
                sequence = store.preview_sequence
                epoch = store.epoch
                fresh = png is not None and status["age_ms"] <= 3000
            if not fresh or sequence <= int(after):
                return self.send_content(204, b"", "image/png")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Sequence", str(sequence))
            self.send_header("X-Frame-ID", str(status["frame_id"]))
            self.send_header("X-Control-Epoch", str(epoch))
            self.send_header("Connection", "close")
            self.end_headers()
            return self.wfile.write(png)
        if path == "/api/frames":
            query = parse_qs(urlsplit(self.path).query, strict_parsing=True)
            if set(query) - {"offset", "limit", "scope"} or any(len(values) != 1 for values in query.values()):
                raise ApiError(400, "page_query", "无效分页参数。")
            offset, limit = query.get("offset", ["0"])[0], query.get("limit", ["30"])[0]
            if not offset.isdecimal() or not limit.isdecimal() or len(offset) > 6 or len(limit) > 2:
                raise ApiError(400, "page_query", "分页参数必须为有界十进制整数。")
            options = {'scope':query.get('scope', ['current'])[0]} if hasattr(store, 'workspace_action') else {}
            return self.send_content(200, json_bytes(store.page(int(offset), int(limit), **options)))
        if path == "/api/export":
            manifest = store.path("dataset_manifest.json")
            if not manifest.is_file():
                raise ApiError(404, "no_export", "请先从界面导出清单。")
            return self.send_content(200, manifest.read_bytes(), attachment="dataset_manifest.json")
        export_match = re.fullmatch(r'/export/([a-f0-9]{32})\.json', path)
        if export_match:
            manifest = store.path(f'dataset_manifest_{export_match[1]}.json')
            if not manifest.is_file():
                raise ApiError(404, 'no_export', '找不到导出清单。')
            return self.send_content(200, manifest.read_bytes(), attachment='dataset_manifest.json')
        if path == "/favicon.ico":
            return self.send_content(204, b"", "image/x-icon")
        media = re.fullmatch(r"/media/([a-f0-9]{32})\.(png|rgb565)", path)
        if media:
            with store.lock:
                row = store.records.get(media[1])
                if row is None:
                    raise ApiError(404, "unknown_frame", "找不到图像。")
                file_path = store.path(row["preview_file" if media[2] == "png" else "file"])
            return self.send_content(200, file_path.read_bytes(), "image/png" if media[2] == "png" else "application/octet-stream")
        video = re.fullmatch(r"/video/([a-f0-9]{32})", path)
        if video:
            with store.lock:
                clip = store.clips.get(video[1])
                if clip is None or clip.get("status") != "labeled":
                    raise ApiError(404, "unknown_clip", "找不到已标注的视频片段。")
                file_path = store.path(clip["video_file"])
            return self.send_path(file_path, "video/x-msvideo")
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                   "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                   "/style.css": ("style.css", "text/css; charset=utf-8"),
                   "/capture.css": ("capture.css", "text/css; charset=utf-8")}
        if path in assets:
            name, content_type = assets[path]
            return self.send_content(200, (Path(__file__).parent / "web" / name).read_bytes(), content_type)
        raise ApiError(404, "not_found", "找不到页面或文件。")

    def _handle(self):
        try:
            self._dispatch()
        except ApiError as error:
            try:
                self.send_content(error.status, json_bytes(dict(ok=False, error=error.code, message=error.message)))
            except OSError:
                pass
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except (ValueError, UnicodeError):
            try:
                self.send_content(400, json_bytes(dict(ok=False, error="invalid_request", message="无效请求格式。")))
            except OSError:
                pass
        except OSError:
            try:
                self.send_content(503, json_bytes(dict(ok=False, error="storage_unavailable", message="读写失败，请检查输出目录与磁盘。")))
            except OSError:
                pass

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="默认仅本机；板端上传时显式使用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "captures")
    parser.add_argument("--max-frames", type=int, default=10000, help="跨会话保存上限，1–100000，默认10000")
    parser.add_argument("--read-timeout", type=float, default=5.0, help="一次完整帧上传限时秒数，1–30")
    parser.add_argument("--usb-port", default='auto', help="自动连接开发板原生 USB；或指定 COM 端口")
    parser.add_argument('--no-usb', action='store_true')
    parser.add_argument('--idle-exit', type=float, default=0, help='无人使用后自动退出的秒数，0为常驻')
    parser.add_argument("--list-usb", action="store_true", help="列出 COM 端口后退出，不打开端口")
    args = parser.parse_args()
    receiver = None
    directory_lock = None
    try:
        if args.list_usb:
            from usb_capture import list_ports
            list_ports()
            return
        ipaddress.IPv4Address(args.bind)
        if not 1 <= args.port <= 65535 or not 1 <= args.read_timeout <= 30 or not 0 <= args.idle_exit <= 3600:
            raise ValueError("port must be 1–65535; read-timeout must be 1–30")
        from managed_capture import ManagedCaptureStore, DataDirectoryLock
        directory_lock = DataDirectoryLock(args.output)
        store = ManagedCaptureStore(args.output, max_frames=args.max_frames, recognition=True, raw_capture_only=True)
        if not args.no_usb:
            from usb_capture import USBReceiver
            receiver = USBReceiver(store, args.usb_port, api_error_type=ApiError)
        server = CaptureHTTPServer((args.bind, args.port), store, read_timeout=args.read_timeout,
                                   usb_receiver=receiver)
        if args.bind == '127.0.0.1':
            # A relocatable hint, never an absolute storage path or credential.
            atomic_json(store.root / '.studio-service.json', {'version': 1, 'port': server.server_port})
    except ImportError:
        parser.exit(2, "USB 模式需要 pyserial：python -m pip install -r HostTools/requirements-usb.txt\n")
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"启动失败：{error}\n")
    print(f"GestureScreen 采集网页：http://{'127.0.0.1' if args.bind == '0.0.0.0' else args.bind}:{args.port}", flush=True)
    print(f"保存目录：{store.root}；恢复 {len(store.records)} 帧；启动状态为暂停。Ctrl+C 退出。", flush=True)
    if args.bind == "0.0.0.0":
        print("已显式监听局域网。板端使用电脑的局域网 IPv4 地址；本程序不修改防火墙。", flush=True)
    if receiver is not None:
        receiver.start()
    idle_stop = threading.Event()
    if args.idle_exit:
        def idle_watch():
            last_busy = time.monotonic()
            while not idle_stop.wait(0.25):
                with store.lock:
                    busy = bool(store.workspace_owner or store.active or store.preview_until > store.clock())
                if busy:
                    last_busy = time.monotonic()
                elif time.monotonic() - last_busy >= args.idle_exit:
                    server.shutdown()
                    return
        threading.Thread(target=idle_watch, name='idle-shutdown', daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        idle_stop.set()
        with store.lock:
            store.active = False
            store._bump()
        if receiver is not None:
            receiver.close()
        deadline = time.monotonic() + args.read_timeout + 1
        while store.pending and time.monotonic() < deadline:
            time.sleep(0.05)
        server.server_close()
        store.close()
        directory_lock.close()


if __name__ == "__main__":
    main()
