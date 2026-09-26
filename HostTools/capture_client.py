"""Native desktop client. HTTP only: the capture service remains the single USB owner."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid
import webbrowser

LABELS = {"张掌": "PALM", "握拳": "FIST", "向左": "POINT_LEFT", "向右": "POINT_RIGHT",
          "V 字": "V_SIGN", "其他手形": "OTHER", "无手": "EMPTY"}
SPLITS = {"训练集": "train", "验证集": "validation", "阈值校准集": "calibration", "独立测试集": "test"}


class CaptureAPI:
    def __init__(self, address):
        if address not in ("http://127.0.0.1:8765", "http://localhost:8765"):
            from urllib.parse import urlsplit
            parsed = urlsplit(address)
            if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.path:
                raise ValueError("客户端仅连接本机 HTTP 采集服务。")
        self.address, self.token = address.rstrip("/"), ""

    def request(self, path, data=None, *, timeout=5):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json", "X-UI-Token": self.token} if body else {}
        try:
            with urlopen(Request(self.address + path, data=body, headers=headers), timeout=timeout) as r:
                raw = r.read()
                if path.startswith("/api/preview.png"):
                    return r.status, dict(r.headers), raw
                result = json.loads(raw)
                if "ui_token" in result:
                    self.token = result["ui_token"]
                return result
        except HTTPError as error:
            try:
                message = json.loads(error.read()).get("message", str(error))
            except (ValueError, UnicodeError):
                message = str(error)
            raise RuntimeError(message) from error


class CaptureClient:
    def __init__(self, root, api):
        self.root, self.api = root, api
        self.owner = uuid.uuid4().hex
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.images = queue.Queue(maxsize=1)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture-action")
        self.observing = False
        self.busy = False
        self.state = {}
        self.last_image = 0.0
        self.display_times = []
        self.photo = None
        root.title("Gesture Studio · 图像观察与数据采集")
        root.geometry("1120x880")
        root.minsize(1060, 840)
        root.configure(bg="#eef2f6")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f6")
        style.configure("TLabel", background="#eef2f6", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=7)
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 19, "bold"))
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Gesture Studio", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(outer, text="原始彩色画面 · 不镜像 · 观察与录制分开").pack(anchor="w", pady=(3, 14))
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        left, right = ttk.Frame(body), ttk.Frame(body, padding=(20, 0, 0, 0))
        left.pack(side="left", fill="both", expand=True)
        right.pack(side="right", fill="y")
        self.canvas = tk.Canvas(left, width=640, height=480, bg="#182531", highlightthickness=0)
        self.canvas.pack(anchor="n")
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.create_rectangle(128, 48, 512, 432, outline="#6ce3ab", width=2)
        self.canvas.create_text(320, 460, text="绿色框为模型区域，左右以此画面为准", fill="white", font=("Microsoft YaHei UI", 10))
        self.frame_text = tk.StringVar(value="等待图像 · 点“开始观察”即可预览，不会保存")
        ttk.Label(left, textvariable=self.frame_text, wraplength=640).pack(anchor="w", pady=10)
        controls = ttk.Frame(left)
        controls.pack(fill="x")
        self.observe_button = ttk.Button(controls, text="开始观察（不存盘）", command=self.toggle_observe)
        self.observe_button.pack(side="left")
        ttk.Button(controls, text="逐帧审阅 / 历史视频", command=lambda: webbrowser.open(api.address)).pack(side="left", padx=10)
        self.metrics = tk.StringVar(value="正在连接本机采集服务…")
        ttk.Label(left, textvariable=self.metrics, wraplength=640).pack(anchor="w", pady=10)
        ttk.Label(left, text="采集标签保留“其他手形 / 无手”的区别，便于后续审查。\n录制不会自动改变模型，也不会把仅观察画面加入数据集。", wraplength=630).pack(anchor="w")

        self.session_name = self.field(right, "会话名称", f"本人_{datetime.now():%Y%m%d_%H%M}")
        self.split = self.choice(right, "整会话用途", list(SPLITS))
        self.new_button = ttk.Button(right, text="新建采集会话", command=self.new_session)
        self.new_button.pack(fill="x", pady=(4, 12))
        self.label = self.choice(right, "本段手势", list(LABELS))
        self.duration = self.field(right, "录制秒数（10–120）", "60")
        self.selection = self.field(right, "抽取训练帧（5–120）", "60")
        self.fps = self.field(right, "请求采样率（0.2–5 fps）", "5")
        self.start_button = ttk.Button(right, text="开始录制", command=self.start_clip)
        self.start_button.pack(fill="x", pady=(10, 4))
        self.stop_button = ttk.Button(right, text="提前停止", command=lambda: self.act("/api/clip", {"action": "stop"}, "已停止，请确认标签。"))
        self.stop_button.pack(fill="x", pady=4)
        self.confirm_button = ttk.Button(right, text="确认标签并生成视频", command=lambda: self.finish_clip(False))
        self.confirm_button.pack(fill="x", pady=4)
        self.discard_button = ttk.Button(right, text="放弃此段（保留原图）", command=lambda: self.finish_clip(True))
        self.discard_button.pack(fill="x", pady=4)
        self.end_button = ttk.Button(right, text="结束会话", command=lambda: self.act("/api/session", {"action": "stop"}, "会话已结束。"))
        self.end_button.pack(fill="x", pady=4)
        self.export_button = ttk.Button(right, text="导出训练清单", command=lambda: self.act("/api/export", {}, "清单已写入保存目录。"))
        self.export_button.pack(fill="x", pady=4)
        self.message = tk.StringVar(value="服务连接后即可开始。")
        ttk.Label(outer, textvariable=self.message, wraplength=1050).pack(fill="x", pady=(12, 0))
        self.path_text = tk.StringVar()
        ttk.Label(outer, textvariable=self.path_text, wraplength=1050).pack(fill="x", pady=3)
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.poll, name="capture-preview", daemon=True).start()
        root.after(40, self.drain)

    @staticmethod
    def field(parent, label, initial):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(5, 2))
        value = tk.StringVar(value=initial)
        ttk.Entry(parent, textvariable=value, width=29).pack(fill="x")
        return value

    @staticmethod
    def choice(parent, label, options):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(5, 2))
        value = tk.StringVar(value=options[0])
        ttk.Combobox(parent, values=options, textvariable=value, state="readonly", width=27).pack(fill="x")
        return value

    def act(self, path, data, success, callback=None):
        if self.busy:
            return
        self.busy = True
        self.message.set("正在处理，请稍候…")
        def work():
            try:
                result = self.api.request(path, data, timeout=120)
                self.events.put(("action", (success, result, callback)))
            except Exception as error:
                self.events.put(("error", str(error)))
        self.executor.submit(work)

    def new_session(self):
        self.act("/api/session", dict(action="new", name=self.session_name.get(), split=SPLITS[self.split.get()],
                 sensor_profile="OV2640_QVGA_RGB565_BE_v1", exposure_profile="auto_exposure_unverified"), "会话已建立，摆好手势后开始录制。")

    def start_clip(self):
        try:
            data = dict(action="start", label=LABELS[self.label.get()], duration_seconds=float(self.duration.get()),
                        selection_count=int(self.selection.get()), fps=float(self.fps.get()))
        except (ValueError, KeyError):
            self.message.set("请填写合法的录制秒数、抽帧数和采样率。")
            return
        self.act("/api/clip", data, "正在录制；保持同一类别，可缓慢改变距离和角度。")

    def finish_clip(self, discard):
        pending = self.state.get("pending_clips", [])
        if not pending:
            return
        self.act("/api/clip", dict(action="discard" if discard else "label", clip_id=pending[0]["clip_id"],
                                  label=LABELS[self.label.get()]), "片段已处理。")

    def toggle_observe(self):
        enabled = not self.observing
        self.act("/api/preview", dict(action="start" if enabled else "stop", owner=self.owner),
                 "正在观察，不保存图像。" if enabled else "已停止观察。", lambda: setattr(self, "observing", enabled))

    def poll(self):
        next_state = next_keep = 0
        sequence = 0
        service_token = None
        while not self.stop.is_set():
            try:
                now = time.monotonic()
                if now >= next_state:
                    state = self.api.request("/api/state")
                    if state.get("ui_token") != service_token:
                        sequence = 0
                        if service_token is not None:
                            self.observing = False
                        service_token = state.get("ui_token")
                    self.events.put(("state", state))
                    next_state = now + 1
                    if "live_preview_v1" not in state.get("capabilities", []):
                        raise RuntimeError("现有服务需要升级并重启。请先结束录制，再运行新版采集服务。")
                if self.observing and now >= next_keep:
                    try:
                        self.api.request("/api/preview", dict(action="keep", owner=self.owner))
                    except Exception:
                        self.observing = False
                        raise
                    next_keep = now + 4
                request_token = service_token
                status, headers, raw = self.api.request(f"/api/preview.png?after={sequence}")
                if status == 200:
                    sequence = int(headers["X-Frame-Sequence"])
                    if self.images.full():
                        try:
                            self.images.get_nowait()
                        except queue.Empty:
                            pass
                    self.images.put_nowait((headers.get("X-Frame-ID", "?"), raw,
                                           int(headers["X-Control-Epoch"]), request_token))
            except Exception as error:
                self.events.put(("connection_error", str(error)))
                self.stop.wait(1)
            self.stop.wait(.08)

    def render_state(self, state):
        if self.state and (self.state.get("epoch") != state.get("epoch") or self.state.get("ui_token") != state.get("ui_token")):
            self.canvas.itemconfigure(self.image_item, image="")
            self.photo = None
            self.display_times = []
            self.last_image = 0
        self.state = state
        active, pending, session = state.get("active"), state.get("pending_clips"), state.get("session")
        for widget, enabled in [(self.new_button, not session and not pending), (self.start_button, session and not active and not pending),
                (self.stop_button, active), (self.confirm_button, pending), (self.discard_button, pending),
                (self.end_button, session and not active and not pending), (self.export_button, not active and not pending)]:
            widget.configure(state="normal" if enabled and not self.busy else "disabled")
        self.observe_button.configure(text="停止观察" if self.observing else "开始观察（不存盘）")
        clip = state.get("active_clip")
        mode = f"录制中 · 本段 {clip['frame_count']} 帧" if clip else "待确认标签" if pending else "会话就绪" if session else "尚未建立采集会话"
        preview = state.get("preview", {})
        fps = preview.get("received_fps", 0)
        self.metrics.set(f"{mode}\n实际接收 {fps:.2f} fps · 保存 {state.get('total', 0)} 帧 · 纳入训练 {state.get('included', 0)} 帧")
        self.path_text.set("保存目录：" + state.get("output_root", ""))

    def drain(self):
        for _ in range(20):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "state":
                self.render_state(value)
            elif kind == "action":
                self.busy = False
                message, result, callback = value
                if callback:
                    callback()
                if "ui_token" in result:
                    self.render_state(result)
                self.message.set(message + (" " + result["manifest"] if "manifest" in result else ""))
            else:
                if kind == "error":
                    self.busy = False
                self.message.set(value)
        try:
            frame_id, raw, epoch, token = self.images.get_nowait()
            if epoch != self.state.get("epoch") or token != self.state.get("ui_token"):
                raise queue.Empty
            self.photo = tk.PhotoImage(data=base64.b64encode(raw)).zoom(2, 2)
            self.canvas.itemconfigure(self.image_item, image=self.photo)
            now = time.monotonic()
            self.last_image = now
            self.display_times = [t for t in self.display_times if now-t < 4] + [now]
            times = self.display_times
            fps = (len(times)-1)/(times[-1]-times[0]) if len(times) > 1 else 0
            self.frame_text.set(f"实时彩色画面 · 帧 {frame_id} · 实际显示 {fps:.2f} fps")
        except queue.Empty:
            if time.monotonic() - self.last_image > 3:
                self.frame_text.set("画面已暂停 / 等待新帧（保留最后一帧供查看）")
        if not self.stop.is_set():
            self.root.after(40, self.drain)

    def close(self):
        if self.busy:
            self.message.set("操作正在提交，请等待结果后再关闭；关闭窗口不能取消已经发送的录制请求。")
            return
        if self.state.get("active"):
            timed = self.state.get("active_clip", {}).get("auto_stop_at")
            detail = "服务会按设定时长停止。" if timed else "本段未设置自动停止，请先停止录制或在网页继续管理。"
            if not messagebox.askyesno("关闭客户端", "关闭窗口不会停止录制。" + detail + "确认关闭？"):
                return
        self.stop.set()
        # Do not stop someone else's recording or shared service. The observation
        # lease expires within 15 seconds even if this best-effort release fails.
        if self.observing:
            def release():
                try:
                    self.api.request("/api/preview", dict(action="stop", owner=self.owner), timeout=2)
                except Exception:
                    pass
            threading.Thread(target=release, daemon=True).start()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def create_root():
    from tk_runtime import configure
    configure()
    return tk.Tk()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    root = create_root()
    CaptureClient(root, CaptureAPI(args.server))
    root.mainloop()


if __name__ == "__main__":
    main()
