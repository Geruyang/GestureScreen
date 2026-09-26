"""Isolated regression checks for Studio's service and download ownership."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "HostTools"))

try:
    import studio_client
except ImportError:
    studio_client = None


@unittest.skipIf(studio_client is None, "PySide6 is not installed in this Python runtime")
class StudioClientAuditTests(unittest.TestCase):
    def test_service_never_uses_gui_extraction_as_working_directory(self):
        with tempfile.TemporaryDirectory() as root, \
                patch.object(studio_client.subprocess, 'Popen') as popen:
            studio_client.start_service(Path(root), 49225, no_usb=True, idle_exit=30)
            self.assertEqual(popen.call_args.kwargs['cwd'], str(Path(root).resolve()))
            self.assertNotEqual(popen.call_args.kwargs['cwd'], str(studio_client.HERE))

    def test_independent_onefile_child_does_not_inherit_parent_runtime_paths(self):
        with tempfile.TemporaryDirectory() as root:
            extraction = Path(root) / '_MEIparent'
            extraction.mkdir()
            data = Path(root) / 'captures'
            environment = {'PATH': str(extraction) + os.pathsep + str(Path(root) / 'system'),
                           'QT_PLUGIN_PATH': str(extraction / 'PySide6/plugins')}
            with patch.object(studio_client.sys, 'frozen', True, create=True), \
                    patch.object(studio_client.sys, '_MEIPASS', str(extraction), create=True), \
                    patch.object(studio_client.sys, 'platform', 'linux'), \
                    patch.dict(studio_client.os.environ, environment), \
                    patch.object(studio_client.subprocess, 'Popen') as popen:
                studio_client.start_service(data, 49226, no_usb=True, idle_exit=30)
                child = popen.call_args.kwargs['env']
                self.assertEqual(child['PYINSTALLER_RESET_ENVIRONMENT'], '1')
                self.assertEqual(child['PATH'], str(Path(root) / 'system'))
                self.assertNotIn('QT_PLUGIN_PATH', child)
                self.assertEqual(studio_client.os.environ['PATH'], environment['PATH'])
                self.assertEqual(popen.call_args.kwargs['cwd'], str(data))

    def test_frozen_default_and_relative_override_follow_executable_not_cwd(self):
        with tempfile.TemporaryDirectory(prefix="portable space-") as root:
            executable = Path(root) / "中文目录" / "GestureStudio.exe"
            with patch.object(studio_client.sys, "frozen", True, create=True), \
                    patch.object(studio_client.sys, "executable", str(executable)):
                self.assertEqual(studio_client.resolve_data_directory(), executable.parent / "captures")
                self.assertEqual(studio_client.resolve_data_directory(Path("my-images")), executable.parent / "my-images")
                self.assertEqual(studio_client.resolve_data_directory(Path(root)), Path(root))

    def test_conflicting_directory_automatically_uses_free_port(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(studio_client, "_read_state", return_value={"occupied": True}), \
                    patch.object(studio_client, "service_ready", side_effect=RuntimeError("另一资料目录")), \
                    patch.object(studio_client, "_free_local_port", return_value=49220):
                self.assertEqual(studio_client.select_service_port(Path(root)), 49220)
                with self.assertRaisesRegex(RuntimeError, "另一资料目录"):
                    studio_client.select_service_port(Path(root), 8765)

    def test_hint_reuses_same_folder_and_stale_hint_never_selects_other_folder(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / '.studio-service.json').write_text(json.dumps({'version': 1, 'port': 49221}))
            with patch.object(studio_client, "_read_state", return_value={"service": True}), \
                    patch.object(studio_client, "service_ready", return_value={}) as ready:
                self.assertEqual(studio_client.select_service_port(folder), 49221)
                ready.assert_called_once_with(49221, expected_root=folder)
            with patch.object(studio_client, "_read_state", side_effect=lambda port: {} if port == 49221 else None), \
                    patch.object(studio_client, "service_ready", side_effect=RuntimeError("旧目录")), \
                    patch.object(studio_client, "_port_listening", return_value=False):
                self.assertEqual(studio_client.select_service_port(folder), 8765)

    def test_non_http_port_and_malformed_hint_are_not_attached(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / '.studio-service.json').write_text('invalid JSON')
            with patch.object(studio_client, "_read_state", return_value=None), \
                    patch.object(studio_client, "_port_listening", return_value=True), \
                    patch.object(studio_client, "_free_local_port", return_value=49222):
                self.assertEqual(studio_client.select_service_port(Path(root)), 49222)

    def test_unwritable_directory_gives_actionable_message(self):
        with patch.object(studio_client.Path, 'mkdir', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(RuntimeError, "有写入权限"):
                studio_client.prepare_data_directory(Path('captures'))

    def test_child_that_loses_launch_race_can_attach_to_winning_service(self):
        losing_child = SimpleNamespace(returncode=2, poll=lambda: 2)
        winner_state = {"model": {"model_sha256": "same-model"}}
        with patch.object(studio_client, "service_ready", side_effect=[None, winner_state]), \
                patch.object(studio_client.time, "sleep"):
            self.assertIs(studio_client.wait_service(49173, losing_child, timeout=1), winner_state)

    def test_same_model_at_wrong_output_root_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="studio-client-root-") as root:
            requested = Path(root) / "requested"
            existing = Path(root) / "other"
            requested.mkdir()
            existing.mkdir()
            state = {"capabilities": ["session_workspace_v2", "raw_capture_v1"],
                     "raw_capture_only": True,
                     "model": {"model_sha256": "frozen-model"},
                     "output_root": str(existing)}
            with patch.object(studio_client, "_read_state", return_value=state), \
                    patch.object(studio_client, "_expected_hash", return_value="frozen-model"):
                with self.assertRaisesRegex(RuntimeError, "另一资料目录"):
                    studio_client.service_ready(49174, requested)
                self.assertIs(studio_client.service_ready(49174, existing), state)

    def test_old_same_model_service_is_rejected_before_attaching(self):
        with tempfile.TemporaryDirectory(prefix="studio-client-old-") as root:
            state = {"capabilities": ["session_workspace_v2"],
                     "model": {"model_sha256": "frozen-model"}, "output_root": root}
            with patch.object(studio_client, "_read_state", return_value=state), \
                    patch.object(studio_client, "_expected_hash", return_value="frozen-model"):
                with self.assertRaisesRegex(RuntimeError, "旧版采集服务"):
                    studio_client.service_ready(49176, Path(root))

    def test_old_auto_finish_service_cannot_masquerade_as_raw_capture(self):
        with tempfile.TemporaryDirectory(prefix="studio-client-old-") as root:
            state = {"capabilities": ["session_workspace_v2", "clip_auto_finish_v1"],
                     "raw_capture_only": False,
                     "model": {"model_sha256": "frozen-model"}, "output_root": root}
            with patch.object(studio_client, "_read_state", return_value=state), \
                    patch.object(studio_client, "_expected_hash", return_value="frozen-model"):
                with self.assertRaisesRegex(RuntimeError, "旧版采集服务"):
                    studio_client.service_ready(49177, Path(root))
            state["capabilities"].append("raw_capture_v1")
            with patch.object(studio_client, "_read_state", return_value=state), \
                    patch.object(studio_client, "_expected_hash", return_value="frozen-model"):
                with self.assertRaisesRegex(RuntimeError, "旧版采集服务"):
                    studio_client.service_ready(49177, Path(root))

    def test_avi_index_must_cover_all_seven_frames(self):
        with tempfile.TemporaryDirectory(prefix="studio-client-avi-") as root:
            movie = Path(root) / "seven.avi"
            header = b"RIFF" + bytes(4) + b"AVI " + b"avih" + (20).to_bytes(4, "little")
            movie.write_bytes(header + bytes(16) + (7).to_bytes(4, "little")
                              + b"idx1" + (7 * 16).to_bytes(4, "little") + bytes(7 * 16))
            self.assertEqual(studio_client._avi_frame_count(movie), 7)
            movie.write_bytes(movie.read_bytes()[:-16])
            with self.assertRaisesRegex(RuntimeError, "索引不一致"):
                studio_client._avi_frame_count(movie)

    def test_shared_profile_download_is_handled_only_by_originating_view(self):
        own_page, foreign_page = object(), object()
        fake_view = SimpleNamespace(page=lambda: own_page)
        item = SimpleNamespace(page=lambda: foreign_page,
                               downloadFileName=lambda: "capture.zip")
        with patch.object(studio_client.QFileDialog, "getSaveFileName") as dialog:
            studio_client.StudioView._download_requested(fake_view, item)
            dialog.assert_not_called()
        own_item = SimpleNamespace(page=lambda: own_page,
                                   downloadFileName=lambda: "capture.zip",
                                   setDownloadDirectory=Mock(), setDownloadFileName=Mock(),
                                   accept=Mock(), cancel=Mock())
        with patch.object(studio_client.QFileDialog, "getSaveFileName",
                          return_value=(str(Path(tempfile.gettempdir()) / "saved.zip"), "")) as dialog:
            studio_client.StudioView._download_requested(fake_view, own_item)
            dialog.assert_called_once()
        own_item.accept.assert_called_once()
        own_item.cancel.assert_not_called()

    def test_double_click_startup_error_is_a_readable_dialog(self):
        with tempfile.TemporaryDirectory(prefix="studio-client-root-") as root:
            fake_app = object()
            with patch.object(studio_client.QApplication, "instance", return_value=fake_app), \
                    patch.object(studio_client, "select_service_port", return_value=49175), \
                    patch.object(studio_client, "_read_state", return_value={"already_running": True}), \
                    patch.object(studio_client, "wait_service", side_effect=RuntimeError("资料目录不一致")), \
                    patch.object(studio_client.QMessageBox, "critical") as dialog:
                result = studio_client.main(["--data-dir", root, "--port", "49175", "--no-usb"])
            self.assertEqual(result, 2)
            dialog.assert_called_once_with(None, "手势采集工作室无法启动", "资料目录不一致")


if __name__ == "__main__":
    unittest.main()
