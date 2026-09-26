"""Portable Qt shell for the same local Gesture Studio web application."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "model/manifest.json"


def application_directory() -> Path:
    # __file__ points into PyInstaller's temporary extraction directory.
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else HERE


def resolve_data_directory(value: Path | None = None) -> Path:
    path = value if value is not None else Path("captures")
    return (path if path.is_absolute() else application_directory() / path).resolve()


def prepare_data_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError as error:
        raise RuntimeError(
            f"无法在程序旁创建或写入资料文件夹：{path}。"
            "请将程序文件夹放到有写入权限的位置后重试。") from error


def _service_hint(data_dir: Path) -> int | None:
    try:
        value = json.loads((data_dir / '.studio-service.json').read_text(encoding='utf-8')).get('port')
        return value if type(value) is int and 1 <= value <= 65535 else None
    except (OSError, ValueError, AttributeError):
        return None


def _port_listening(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.25):
            return True
    except OSError:
        return False


def select_service_port(data_dir: Path, requested: int | None = None) -> int:
    """Reuse only a compatible service for this folder, otherwise find a free port."""
    candidates = [requested] if requested is not None else list(dict.fromkeys([_service_hint(data_dir), 8765]))
    for port in candidates:
        if port is None:
            continue
        state = _read_state(port)
        if state is not None:
            try:
                service_ready(port, expected_root=data_dir)
                return port  # Also reuse a compatible service whose model is still loading.
            except RuntimeError:
                if requested is not None:
                    raise
                continue
        if not _port_listening(port) and (requested is not None or port == 8765):
            return port
        if requested is not None:
            raise RuntimeError(f"指定的端口 {port} 已被占用。请关闭占用程序，或直接双击本程序自动连接。")
    return _free_local_port()


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def _read_state(port: int) -> dict | None:
    try:
        with urlopen(_url(port, "/api/state"), timeout=1.5) as response:
            return json.load(response)
    except (OSError, URLError, ValueError):
        return None


def _expected_hash() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["files_sha256"]["gesture_v12_int8.tflite"]


def service_ready(port: int, expected_root: Path | None = None) -> dict | None:
    """None means startup is still pending, not an incompatible service."""
    state = _read_state(port)
    if state is None:
        return None
    if "session_workspace_v2" not in (state.get("capabilities") or []):
        raise RuntimeError(f"端口 {port} 已由其他服务占用。请指定另一个 --port。")
    if "raw_capture_v1" not in state["capabilities"] or state.get("raw_capture_only") is not True:
        raise RuntimeError(
            f"端口 {port} 仍运行旧版采集服务。请先关闭旧版客户端及其后台服务，"
            "再启动此版本；也可指定另一个 --port。")
    if expected_root is not None:
        actual_root = state.get("output_root")
        if (not isinstance(actual_root, str) or
                os.path.normcase(str(Path(actual_root).resolve())) !=
                os.path.normcase(str(expected_root.resolve()))):
            raise RuntimeError(
                f"端口 {port} 已连接另一资料目录（{actual_root or '未知'}）。"
                "请指定另一个 --port，或使用该服务的 --data-dir。")
    model = state.get("model") or {}
    if model.get("model_sha256"):
        if model["model_sha256"].lower() != _expected_hash().lower():
            raise RuntimeError(f"端口 {port} 的模型与此程序不同。请指定另一个 --port。")
        return state
    if state.get("model_error"):
        raise RuntimeError(str(state["model_error"]))
    return None


def start_service(data_dir: Path, port: int, *, no_usb: bool, idle_exit: int) -> subprocess.Popen:
    data_dir.mkdir(parents=True, exist_ok=True)
    logdir = data_dir / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / "studio-server.log"
    cmd = ([sys.executable, "--studio-server"] if getattr(sys, "frozen", False)
           else [sys.executable, str(HERE / "capture_server.py")])
    cmd += ["--output", str(data_dir), "--port", str(port), "--idle-exit", str(idle_exit)]
    if no_usb:
        cmd.append("--no-usb")
    child_env = dict(os.environ, PYTHONUTF8="1")
    if getattr(sys, "frozen", False):
        # PyInstaller 6.9+ otherwise shares the GUI's onefile extraction.
        # The service may outlive that GUI while another browser stays open.
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        # The independent onefile child must not load DLLs from this GUI's
        # extraction directory, or keep that directory open as its cwd.
        extraction = Path(sys._MEIPASS).resolve()
        def from_extraction(value):
            return bool(value) and Path(value).resolve().is_relative_to(extraction)
        child_env['PATH'] = os.pathsep.join(p for p in child_env.get('PATH', '').split(os.pathsep)
                                           if not from_extraction(p))
        for key in ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QTWEBENGINEPROCESS_PATH',
                    'QTWEBENGINE_RESOURCES_PATH', 'QTWEBENGINE_LOCALES_PATH'):
            if any(from_extraction(p) for p in child_env.get(key, '').split(os.pathsep)):
                child_env.pop(key, None)
    with logfile.open("ab") as stream:
        dll_api = None
        previous_dll_directory = None
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            import ctypes
            dll_api = ctypes.WinDLL('kernel32', use_last_error=True)
            dll_api.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
            dll_api.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
            length = dll_api.GetDllDirectoryW(0, None)
            buffer = ctypes.create_unicode_buffer(length + 1)
            dll_api.GetDllDirectoryW(len(buffer), buffer)
            previous_dll_directory = buffer.value or None
            if not dll_api.SetDllDirectoryW(None):
                raise ctypes.WinError(ctypes.get_last_error())
        try:
            return subprocess.Popen(cmd, cwd=str(data_dir.resolve()), stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                    env=child_env)
        finally:
            if dll_api is not None:
                dll_api.SetDllDirectoryW(previous_dll_directory)


def wait_service(port: int, child: subprocess.Popen | None, timeout: float = 30.0,
                 expected_root: Path | None = None) -> dict:
    deadline = time.monotonic() + timeout
    child_exit_deadline = None
    while time.monotonic() < deadline:
        state = service_ready(port, expected_root)
        if state is not None:
            return state
        if child is not None and child.poll() is not None:
            # Two windows can launch before either onefile child has bound the
            # port. The child that loses the directory lock exits first; give
            # the winner a short opportunity to publish the compatible API.
            if child_exit_deadline is None:
                child_exit_deadline = min(deadline, time.monotonic() + 5.0)
            if time.monotonic() >= child_exit_deadline:
                raise RuntimeError(f"采集服务启动失败（退出码 {child.returncode}），请查看资料目录的 logs/studio-server.log。")
        time.sleep(0.15)
    raise RuntimeError("采集服务和模型未在 30 秒内就绪，请查看资料目录的 logs/studio-server.log。")


def _post(port: int, token: str, path: str, payload: dict, timeout: float = 2.0) -> dict:
    request = Request(_url(port, path), data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "X-UI-Token": token})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _synthetic_preview(port: int) -> dict:
    """Exercise the packaged inference path without saving a training sample."""
    state = _read_state(port) or {}
    epoch = state.get("epoch")
    if not isinstance(epoch, int):
        raise RuntimeError("自检无法读取采集代际")
    row_data = bytearray(320 * 240 * 2)
    for y in range(240):
        green = (y * 63) // 239
        for x in range(320):
            value = ((x * 31 // 319) << 11) | (green << 5) | ((x + y) * 31 // 558)
            position = (y * 320 + x) * 2
            row_data[position] = value >> 8
            row_data[position + 1] = value & 255
    frame_id = 7031
    headers = {"Content-Type": "application/octet-stream", "X-Width": "320", "X-Height": "240",
               "X-Pixel-Format": "RGB565_BE", "X-Device-ID": "portable-selftest",
               "X-Frame-ID": str(frame_id), "X-Capture-Ms": "1", "X-Control-Epoch": str(epoch)}
    request = Request(_url(port, "/api/frames"), data=bytes(row_data), method="POST", headers=headers)
    with urlopen(request, timeout=5) as response:
        upload = json.load(response)
    if upload.get("preview_only") is not True:
        raise RuntimeError("合成预览帧意外进入保存路径")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with urlopen(_url(port, "/api/live"), timeout=1) as response:
            live = json.load(response)
        row = live.get("recognition")
        if row and row.get("frame_id") == frame_id:
            if (row.get("quality_ok") is not True or not isinstance(row.get("class_index"), int)
                    or not 0 <= row["class_index"] < 6
                    or not isinstance(row.get("confidence"), (int, float))
                    or not 0 <= row["confidence"] <= 1 or live.get("model_error")):
                raise RuntimeError("合成预览帧的推理输出无效")
            return {"frame_id": frame_id, "class_index": row["class_index"],
                    "confidence": row["confidence"], "quality_ok": True,
                    "preview_only": True, "model_error": live.get("model_error")}
        if live.get("model_error"):
            raise RuntimeError(f"合成推理失败：{live['model_error']}")
        time.sleep(0.02)
    raise RuntimeError("合成预览帧未得到新鲜模型结果")


def _synthetic_recording_frame(number: int) -> bytes:
    color = (((number * 3) & 31) << 11) | (((number * 5) & 63) << 5) | ((number * 7) & 31)
    return color.to_bytes(2, "big") * (320 * 240)


def _upload_recording_frame(port: int, frame_id: int, epoch: int) -> dict:
    headers = {"Content-Type": "application/octet-stream", "X-Width": "320", "X-Height": "240",
               "X-Pixel-Format": "RGB565_BE", "X-Device-ID": "portable-selftest",
               "X-Frame-ID": str(frame_id), "X-Capture-Ms": str(frame_id * 250),
               "X-Control-Epoch": str(epoch)}
    request = Request(_url(port, "/api/frames"), data=_synthetic_recording_frame(frame_id),
                      method="POST", headers=headers)
    with urlopen(request, timeout=5) as response:
        result = json.load(response)
        if response.status != 201 or result.get("duplicate") or result.get("preview_only"):
            raise RuntimeError("合成录制帧未保存到隔离临时片段")
        return result


def _qt_wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _javascript(view: QWebEngineView, source: str, timeout_ms: int = 3000):
    loop, result = QEventLoop(), {"done": False, "value": None}
    def received(value):
        result.update(done=True, value=value)
        loop.quit()
    view.page().runJavaScript(f"JSON.stringify({source})", received)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    if not result["done"]:
        raise TimeoutError("网页脚本未及时响应")
    return json.loads(result["value"]) if isinstance(result["value"], str) else None


class LocalPage(QWebEnginePage):
    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self.port = port

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if not is_main_frame:
            return False
        if url.scheme() == "about" and url.toString() == "about:blank":
            return True
        return url.scheme() == "http" and url.host() == "127.0.0.1" and url.port() == self.port


class StudioView(QWebEngineView):
    """Closing waits for this web window's explicit session cleanup."""
    def __init__(self, port: int):
        super().__init__()
        self.port = port
        self._closing = False
        self._permit_close = False
        self._close_success = False
        self._close_done = threading.Event()
        self._close_deadline = 0.0
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(50)
        self._close_timer.timeout.connect(self._poll_close)
        self.setPage(LocalPage(port, self))
        self.page().profile().downloadRequested.connect(self._download_requested)

    def createWindow(self, window_type):
        return None

    def _download_requested(self, item) -> None:
        # The default profile is shared by all StudioView windows. Only the
        # window that initiated this download may show a save dialog.
        if item.page() != self.page():
            return
        name = Path(item.downloadFileName() or "download.bin").name
        target, _ = QFileDialog.getSaveFileName(self, "保存下载文件", name)
        if target:
            item.setDownloadDirectory(str(Path(target).parent))
            item.setDownloadFileName(Path(target).name)
            item.accept()
        else:
            item.cancel()

    def _close_workspace(self, details) -> None:
        try:
            if isinstance(details, dict) and details.get("owner") and details.get("token"):
                try:
                    _post(self.port, details["token"], "/api/preview",
                          {"action": "stop", "owner": details["owner"]})
                except (OSError, HTTPError, ValueError):
                    pass
                response = _post(self.port, details["token"], "/api/workspace",
                                 {"action": "close", "owner": details["owner"]})
                self._close_success = response.get("ok") is True
        except (OSError, HTTPError, ValueError):
            # Server expiry freezes the session if the close request cannot arrive.
            pass
        finally:
            self._close_done.set()

    def _close_details(self, details) -> None:
        try:
            details = json.loads(details) if isinstance(details, str) else None
        except ValueError:
            details = None
        threading.Thread(target=self._close_workspace, args=(details,), daemon=True,
                         name="studio-window-close").start()

    def _poll_close(self) -> None:
        if not self._close_done.is_set() and time.monotonic() < self._close_deadline:
            return
        self._close_timer.stop()
        self._permit_close = True
        self.close()  # A fresh QCloseEvent; the ignored original is never reused.

    def closeEvent(self, event) -> None:
        if self._permit_close:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self._close_deadline = time.monotonic() + 3.0
        self._close_timer.start()
        self.page().runJavaScript(
            "JSON.stringify((()=>{if(typeof closing!=='undefined')closing=true;"
            "if(typeof hideGesture==='function')hideGesture();"
            "return {owner:window.studioOwner||'',"
            "token:(typeof state!=='undefined'&&state?state.ui_token:'')};})())",
            self._close_details)


def _free_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _avi_frame_count(path: Path) -> int:
    """Check the written AVI header and index contain the same frame count."""
    data = path.read_bytes()
    if len(data) < 64 or data[:4] != b"RIFF" or data[8:12] != b"AVI ":
        raise RuntimeError("合成 AVI 文件头无效")
    header = data.find(b"avih", 12)
    index = data.rfind(b"idx1")
    if header < 0 or index < 0 or header + 28 > len(data) or index + 8 > len(data):
        raise RuntimeError("合成 AVI 缺少帧数或索引")
    count = int.from_bytes(data[header + 24:header + 28], "little")
    index_size = int.from_bytes(data[index + 4:index + 8], "little")
    if count < 1 or index_size != 16 * count or index + 8 + index_size != len(data):
        raise RuntimeError("合成 AVI 帧数与索引不一致")
    return count


def _self_test(data_dir: Path, report_path: Path) -> int:
    """Exercise two real Qt pages, service handoff and temporary cleanup."""
    report: dict = {"ok": False, "service_ready": False, "qt_document_ready": False,
                    "model_identity": None, "workspace_created": False,
                    "cleanup_request": False, "temporary_removed": False,
                    "second_view_attached": False, "second_after_first_close": False,
                    "second_close_complete": False, "synthetic_inference": None,
                    "recording_finished": False, "saved_history": False,
                    "raw_frames_saved": False, "avi_frames": None,
                    "exported_samples": None, "retained_history_preserved": False,
                    "server_idle_exit": False}
    data_dir.mkdir(parents=True, exist_ok=True)
    child = None
    view = None
    second_view = None
    try:
        with tempfile.TemporaryDirectory(prefix="studio-self-test-", dir=data_dir,
                                         ignore_cleanup_errors=True) as temporary:
            test_dir, port = Path(temporary), _free_local_port()
            child = start_service(test_dir, port, no_usb=True, idle_exit=3)
            state = wait_service(port, child, expected_root=test_dir)
            report["service_ready"] = True
            report["model_identity"] = state.get("model")
            with urlopen(_url(port, "/"), timeout=2) as document:
                report["http_document_status"] = document.status
            app = QApplication.instance() or QApplication(sys.argv)
            view = StudioView(port)
            view.resize(1000, 700)
            load = {"done": False, "ok": False}
            loop = QEventLoop()
            target_url = _url(port, "/")
            def loaded(ok):
                current_url = view.url().toString()
                if bool(ok) or current_url == target_url:
                    load.update(done=True, ok=bool(ok))
                    report["qt_loaded_url"] = current_url
                    loop.quit()
                else:
                    report["qt_ignored_initial_load"] = report.get("qt_ignored_initial_load", 0) + 1
            view.loadFinished.connect(loaded)
            view.page().loadingChanged.connect(
                lambda info: report.update(qt_load_error=info.errorString(),
                                           qt_load_code=int(info.errorCode()),
                                           qt_load_url=info.url().toString())
                if info.status().name == "LoadFailedStatus" else None)
            view.load(QUrl(target_url))
            view.show()
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            if not load["done"] or not load["ok"]:
                raise RuntimeError("QtWebEngine 未加载采集网页")
            report["qt_script_smoke"] = [_javascript(view, expression) for expression in
                                         ("2+2", "document.title", "document.readyState",
                                          "document.documentElement.outerHTML.slice(0,120)")]
            details = None
            for _ in range(50):
                details = _javascript(view, "({title:document.title,owner:window.studioOwner||'',"
                                      "token:(typeof state!=='undefined'&&state?state.ui_token:''),"
                                      "model:document.getElementById('model-info')?.textContent||'',"
                                      "total:document.getElementById('total')?.textContent||''})")
                if details and details["owner"] and details["token"] and _expected_hash() in details["model"]:
                    break
                _qt_wait(100)
            report["qt_dom_details"] = {"title": details.get("title") if isinstance(details, dict) else None,
                                         "has_owner": bool(details and details.get("owner")),
                                         "has_token": bool(details and details.get("token")),
                                         "model": (details.get("model") or "")[:240] if isinstance(details, dict) else None,
                                         "total": details.get("total") if isinstance(details, dict) else None}
            if not details or _expected_hash() not in details["model"] or not details["owner"] or not details["token"]:
                raise RuntimeError("网页未显示同一模型或未建立窗口会话")
            report["qt_document_ready"] = ("手势" in details["title"] and details["total"] == "0")
            if not report["qt_document_ready"]:
                raise RuntimeError("网页标题或临时计数不正确")
            created = _post(port, details["token"], "/api/session",
                            {"action": "new", "owner": details["owner"], "name": "便携包自检",
                             "split": "train", "sensor_profile": "self-test", "exposure_profile": "self-test"})
            session = created.get("session") or {}
            session_id = session.get("session_id")
            session_dir = test_dir / "sessions" / str(session_id)
            report["workspace_created"] = bool(session_id and session_dir.is_dir())
            if not report["workspace_created"]:
                raise RuntimeError("临时会话未真实创建")
            second_view = StudioView(port)
            second_view.resize(800, 600)
            second_view.load(QUrl(target_url))
            second_view.show()
            second_details = None
            for _ in range(60):
                second_details = _javascript(
                    second_view,
                    "({title:document.title,owner:window.studioOwner||'',"
                    "token:(typeof state!=='undefined'&&state?state.ui_token:''),"
                    "model:document.getElementById('model-info')?.textContent||'',"
                    "observing:(typeof observing!=='undefined'&&observing)})")
                if (second_details and second_details["owner"] != details["owner"]
                        and second_details["token"] == details["token"]
                        and _expected_hash() in second_details["model"]
                        and second_details["observing"]):
                    break
                _qt_wait(100)
            report["second_view_attached"] = bool(
                second_details and second_details["owner"] != details["owner"]
                and second_details["token"] == details["token"]
                and _expected_hash() in second_details["model"]
                and second_details["observing"])
            if not report["second_view_attached"]:
                raise RuntimeError("第二个 Qt 窗口未建立独立观察租约或模型页面")
            report["synthetic_inference"] = _synthetic_preview(port)
            started = _post(port, details["token"], "/api/clip",
                            {"action": "start", "owner": details["owner"], "fps": 5,
                             "label": "POINT_LEFT", "duration_seconds": 60})
            clip_id = (started.get("active_clip") or {}).get("clip_id")
            if not clip_id:
                raise RuntimeError("合成片段未开始")
            recording_epoch = started["epoch"]
            for number in range(1, 8):
                _upload_recording_frame(port, 8000 + number, recording_epoch)
                time.sleep(0.25)
            before_finish = _read_state(port) or {}
            if (before_finish.get("total") != 7 or before_finish.get("captured_total") != 7
                    or before_finish.get("included") != 0 or before_finish.get("exportable_total") != 0):
                raise RuntimeError("合成录制阶段的待整理计数不正确")
            _post(port, details["token"], "/api/clip",
                  {"action": "finish", "owner": details["owner"]})
            deadline = time.monotonic() + 10
            finished = None
            while time.monotonic() < deadline:
                candidate = _read_state(port) or {}
                if (not candidate.get("pending_clips") and candidate.get("included") == 0
                        and candidate.get("exportable_total") == 7 and
                        any(row.get("clip_id") == clip_id and row.get("frame_count") == 7
                                and row.get("selected_count") is None
                            for row in candidate.get("recent_clips", []))):
                    finished = candidate
                    break
                time.sleep(0.05)
            report["recording_finished"] = finished is not None
            if not report["recording_finished"]:
                raise RuntimeError("提前结束后未将全部 7 帧整理完成")
            clip = next(row for row in finished["recent_clips"] if row.get("clip_id") == clip_id)
            report["avi_frames"] = _avi_frame_count(test_dir / clip["video_file"])
            if report["avi_frames"] != 7:
                raise RuntimeError("合成 AVI 未包含全部 7 帧")
            raw_files = list((session_dir / "frames").glob("*.rgb565"))
            png_files = list((session_dir / "frames").glob("*.png"))
            expected_frames = {_synthetic_recording_frame(8000 + number) for number in range(1, 8)}
            report["raw_frames_saved"] = (len(raw_files) == len(png_files) == 7
                                          and {path.read_bytes() for path in raw_files} == expected_frames)
            if not report["raw_frames_saved"]:
                raise RuntimeError("隔离片段的 RGB565/PNG 原始画面未完整保存")
            saved = _post(port, details["token"], "/api/session",
                          {"action": "save", "owner": details["owner"]})
            report["saved_history"] = bool(saved.get("session_saved") and
                                           saved.get("history_total") == 7 and
                                           saved.get("history_included") == 0 and session_dir.is_dir())
            if not report["saved_history"]:
                raise RuntimeError("合成片段未保存到隔离历史")
            exported = _post(port, details["token"], "/api/export",
                             {"scope": "current", "owner": details["owner"]})
            with urlopen(_url(port, exported["download"]), timeout=3) as response:
                export_manifest = json.load(response)
            report["exported_samples"] = len(export_manifest.get("samples", []))
            if (exported.get("purpose") != "raw_capture_unreviewed"
                    or export_manifest.get("purpose") != "raw_capture_unreviewed"
                    or export_manifest.get("training_ready") is not False
                    or exported.get("sample_count") != 7 or report["exported_samples"] != 7
                    or any(row.get("excluded") is not True for row in export_manifest["samples"])):
                raise RuntimeError("隔离历史导出清单不是 7 张未审核原始帧")
            next_session = _post(port, details["token"], "/api/session",
                                 {"action": "new", "owner": details["owner"],
                                  "name": "便携包关窗清理", "split": "train",
                                  "sensor_profile": "self-test", "exposure_profile": "self-test"})
            temporary_id = (next_session.get("session") or {}).get("session_id")
            temporary_dir = test_dir / "sessions" / str(temporary_id)
            if not temporary_id or not temporary_dir.is_dir():
                raise RuntimeError("关窗清理验证用的临时会话未建立")
            view.close()
            deadline = time.monotonic() + 4
            while not view._permit_close and time.monotonic() < deadline:
                _qt_wait(50)
            report["cleanup_request"] = view._close_success and view._permit_close
            if not report["cleanup_request"]:
                raise RuntimeError("Qt 关窗未完成真实 workspace close 请求")
            post = _read_state(port) or {}
            report["temporary_removed"] = not temporary_dir.exists() and post.get("total") == 0
            if not report["temporary_removed"]:
                raise RuntimeError("关闭窗口后临时会话未被清除")
            report["retained_history_preserved"] = bool(
                session_dir.is_dir() and post.get("history_total") == 7 and
                post.get("history_included") == 0)
            if not report["retained_history_preserved"]:
                raise RuntimeError("关窗误删已保存合成历史")
            _qt_wait(400)
            after_first = _javascript(
                second_view,
                "({title:document.title,owner:window.studioOwner||'',"
                "model:document.getElementById('model-info')?.textContent||'',"
                "observing:(typeof observing!=='undefined'&&observing),"
                "ready:document.readyState})")
            report["second_after_first_close"] = bool(
                after_first and after_first["owner"] == second_details["owner"]
                and _expected_hash() in after_first["model"]
                and after_first["observing"] and after_first["ready"] == "complete"
                and _read_state(port))
            if not report["second_after_first_close"]:
                raise RuntimeError("首窗口关闭后第二窗口无法继续读取同一模型页面")
            view.deleteLater()
            view = None
            second_view.close()
            deadline = time.monotonic() + 4
            while not second_view._permit_close and time.monotonic() < deadline:
                _qt_wait(50)
            report["second_close_complete"] = second_view._permit_close
            if not report["second_close_complete"]:
                raise RuntimeError("第二窗口未完成关闭")
            second_view.deleteLater()
            second_view = None
            try:
                child.wait(timeout=9)
                report["server_idle_exit"] = child.returncode == 0
            except subprocess.TimeoutExpired:
                report["server_idle_exit"] = False
            report["ok"] = all(report[k] for k in ("service_ready", "qt_document_ready",
                                                   "workspace_created", "cleanup_request",
                                                   "temporary_removed", "second_view_attached",
                                                   "second_after_first_close", "second_close_complete",
                                                   "synthetic_inference", "recording_finished",
                                                   "saved_history", "raw_frames_saved", "avi_frames",
                                                   "exported_samples",
                                                   "retained_history_preserved", "server_idle_exit"))
    except Exception as error:
        report["error"] = str(error)
    finally:
        if view is not None:
            view.close()
        if second_view is not None:
            second_view.close()
        if child is not None and child.poll() is None:
            # Only the isolated child created by this self-test may be stopped.
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["ok"] else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-report", type=Path)
    parser.add_argument("--no-usb", action="store_true")
    parser.add_argument("--self-test-close-report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    data_dir = resolve_data_directory(args.data_dir)
    if args.self_test_close_report and (not args.no_usb or (data_dir / 'sessions').exists()):
        parser.error('退出自检仅允许 --no-usb 和全新的隔离资料目录')
    if args.self_test:
        return _self_test(data_dir, args.self_test_report or data_dir / "self-test-report.json")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port 必须为 1 到 65535")
    app = QApplication.instance() or QApplication(sys.argv)
    child = None
    try:
        prepare_data_directory(data_dir)
        port = select_service_port(data_dir, args.port)
        if _read_state(port) is None:
            child = start_service(data_dir, port, no_usb=args.no_usb, idle_exit=30)
        try:
            wait_service(port, child, expected_root=data_dir)
        except RuntimeError:
            # Another launch may win the directory lock on a different automatic
            # port. Its server publishes a hint only after binding successfully.
            hint = _service_hint(data_dir)
            if args.port is not None or hint is None or hint == port:
                raise
            wait_service(hint, None, timeout=5, expected_root=data_dir)
            port = hint
    except Exception as error:
        if child is not None and child.poll() is None:
            child.terminate()  # Startup failure only; never on normal window close.
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        QMessageBox.critical(None, "手势采集工作室无法启动", str(error))
        return 2
    view = StudioView(port)
    view.setWindowTitle("Gesture Studio · 手势采集工作室")
    screen = app.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        view.resize(max(1, min(1280, area.width() - 40)),
                    max(1, min(900, area.height() - 60)))
    else:
        view.resize(1120, 760)
    if args.self_test_close_report:
        # Exercise the real normal-close path while the service is still alive.
        def test_close_when_ready():
            current = _read_state(port) or {}
            if current.get('workspace_busy'):
                view.close()
            else:
                QTimer.singleShot(100, test_close_when_ready)
        QTimer.singleShot(500, test_close_when_ready)
        QTimer.singleShot(20000, view.close)
    view.load(QUrl(_url(port, "/")))
    view.show()
    result = app.exec()
    close_success = view._close_success
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    if args.self_test_close_report:
        args.self_test_close_report.parent.mkdir(parents=True, exist_ok=True)
        args.self_test_close_report.write_text(json.dumps({
            'close_success': close_success, 'port': port, 'data_root': str(data_dir),
            'gui_extraction': str(getattr(sys, '_MEIPASS', HERE)),
            'server_alive_after_window_close': _read_state(port) is not None,
        }, indent=2), encoding='utf-8')
    return result


if __name__ == "__main__":
    if "--studio-server" in sys.argv:
        sys.argv.remove("--studio-server")
        from capture_server import main as server_main
        raise SystemExit(server_main())
    raise SystemExit(main())
