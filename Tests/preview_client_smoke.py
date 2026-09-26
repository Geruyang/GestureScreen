"""Visible native-window smoke with synthetic colour frames. No board access."""
import sys
from pathlib import Path
import json
import tempfile
import threading
import time
import tkinter as tk
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HostTools"))
from capture_server import CaptureHTTPServer, CaptureStore
from capture_client import CaptureAPI, CaptureClient, create_root

out = Path(__file__).resolve().parents[1] / "Build/reader-20260922/client"
out.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    store = CaptureStore(Path(folder))
    server = CaptureHTTPServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
    thread.start()
    root = create_root()
    client = CaptureClient(root, CaptureAPI(f"http://127.0.0.1:{server.server_address[1]}"))
    root.title("Gesture Studio · 合成画面界面测试（非相机）")
    results = {}

    def feed(index=0):
        if store.preview_status()["enabled"] or store.active:
            # Colour bars with changing small frame marker; no real/user image.
            raw = b"".join((b"\xf8\x00"*80 + b"\x07\xe0"*80 + b"\x00\x1f"*80 + b"\xff\xff"*80) for _ in range(240))
            raw = bytes((index & 255, 128)) + raw[2:]
            ticket = None
            try:
                ticket = store.begin(dict(epoch=store.epoch, device_id="synthetic", frame_id=index, capture_ms=index*230))
                store.commit(ticket, raw)
            except Exception:
                pass
            finally:
                if ticket:
                    store.release(ticket)
        root.after(230, lambda: feed(index+1))

    def check_preview():
        results["observation_no_records"] = len(store.records) == 0
        results["displayed_multiple_frames"] = len(client.display_times) >= 5
        results["shown_fps"] = client.frame_text.get()
        try:
            from PIL import ImageGrab
            root.update()
            x,y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height())).save(out/"desktop-synthetic.png")
            results["screenshot"] = str(out/"desktop-synthetic.png")
        except (ImportError, OSError) as error:
            results["screenshot"] = f"unavailable: {error}"
            try:
                from window_capture import save_window
                save_window(root, out/"desktop-synthetic.png")
                results["screenshot"] = str(out/"desktop-synthetic.png")
            except (ImportError, OSError) as window_error:
                results["screenshot"] += f"; {window_error}"
        client.new_session()

    def record():
        client.duration.set("10")
        client.selection.set("5")
        client.start_clip()

    def stop_record():
        results["recording_saved"] = len(store.records) >= 4
        client.act("/api/clip", {"action":"stop"}, "合成采集结束")

    def finish():
        if client.busy:
            root.after(300, finish)
            return
        pending = list(store.pending_clips)
        if pending:
            client.act("/api/clip", {"action":"label", "clip_id":pending[0], "label":"PALM"}, "合成标注完成")
        root.after(1800, done)

    def done():
        results["labeled_video"] = any(c.get("status")=="labeled" for c in store.clips.values())
        results["status"] = "PASS" if all(results.get(k) for k in ("observation_no_records", "displayed_multiple_frames", "recording_saved", "labeled_video")) else "FAIL"
        (out/"desktop-smoke.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
        client.state["active"] = False
        client.close()

    root.after(400, client.toggle_observe)
    root.after(600, feed)
    root.after(2600, check_preview)
    root.after(3300, record)
    root.after(5200, stop_record)
    root.after(5900, finish)
    root.mainloop()
    server.shutdown()
    server.server_close()
print(json.dumps(results, ensure_ascii=False))
raise SystemExit(0 if results["status"] == "PASS" else 1)
