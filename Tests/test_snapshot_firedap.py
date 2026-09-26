"""Finite SWD snapshot entry tests: mock process and offline parsing only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "Tools/snapshot_firedap.ps1"
parser = argparse.ArgumentParser()
parser.add_argument("--vcvars", default=r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat")
parser.add_argument("--powershell", default="powershell.exe")
args, remaining = parser.parse_known_args()


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT / "Build/agent-team/round5/executor"
        base.mkdir(parents=True, exist_ok=True)
        cls.evidence = base / "mock-results"
        cls.directory = tempfile.TemporaryDirectory(prefix="snapshot mock ", dir=base)
        cls.output = Path(cls.directory.name)
        cls.mock = cls.output / "mock openocd.exe"
        source = ROOT / "Tests/fixtures/snapshot_openocd_mock.c"
        vcvars = str(Path(args.vcvars).resolve())
        if any(re.search(r'["%!^\r\n]', str(p)) for p in (source, cls.mock, vcvars)):
            raise ValueError("unsupported compiler batch path")
        command = cls.output / "build_mock.cmd"
        command.write_text('@echo off\nsetlocal\ncall "' + vcvars + '" > vcvars.log 2>&1\n'
            'if errorlevel 1 exit /b 1\nset "CL="\nset "_CL_="\n'
            'cl /nologo /std:c11 /utf-8 /W4 /WX /UNDEBUG /D_CRT_SECURE_NO_WARNINGS "' + str(source) +
            '" /Fe:"' + str(cls.mock) + '" > compile.log 2>&1\nexit /b %errorlevel%\n', encoding="utf-8")
        subprocess.run([os.environ["ComSpec"], "/d", "/c", "build_mock.cmd"], cwd=cls.output, check=True)
        cls.scripts = cls.output / "mock scripts"
        for relative in ("interface/cmsis-dap.cfg", "target/stm32f4x.cfg"):
            p = cls.scripts / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# inert fixture; mock executable does not contact hardware\n")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_entry(self, mode="success", execute=True, extra=(), existing_flash=False):
        output = self.output / (self._testMethodName + " output with spaces")
        if existing_flash:
            output.mkdir(parents=True, exist_ok=True)
            (output / "target-flash.bin").write_bytes(b"old file must remain unchanged")
        command = [args.powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ENTRY),
                   "-OpenOCD", str(self.mock), "-Scripts", str(self.scripts),
                   "-OutputDir", str(output), "-TimeoutSeconds", "1"]
        if execute:
            command.append("-Execute")
        env = dict(os.environ, GS_SNAPSHOT_MOCK_MODE=mode)
        process = subprocess.run(command + list(extra), env=env, capture_output=True, timeout=10)
        path = output / "result.json"
        result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if output.exists():
            shutil.copytree(output, self.evidence / self._testMethodName, dirs_exist_ok=True)
            (self.evidence / self._testMethodName / "test-evidence.json").write_text(json.dumps(dict(
                source="synthetic_openocd_process", hardware_contacted=False,
                entry_exit_code=process.returncode, mock_executable=str(self.mock)), indent=2) + "\n")
        return process, result, output

    def test_default_offline_plan_has_no_readback_or_init(self):
        process, result, output = self.run_entry(execute=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["outcome"], "offline_plan_checked")
        self.assertFalse(result["hardware_contact_attempted"])
        self.assertFalse(result["readback_observed"])
        self.assertIsNone(result["readback"])
        session = (output / "session.tcl").read_text()
        self.assertNotRegex(session, r"(?m)^\s*init\s*$")
        self.assertNotIn("read_memory", session)

    def test_success_values_are_printed_and_parsed(self):
        process, result, output = self.run_entry()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(result["identity_matches_expected"])
        self.assertTrue(result["readback_observed"])
        self.assertEqual(result["readback"]["FLASH_KIB"], "1024")
        self.assertEqual(result["readback"]["CPUID"], "0x410fc241")
        self.assertEqual(result["openocd_exit_code"], 0)
        self.assertEqual(Path(result["openocd_executable"]), self.mock)
        self.assertIn("GS_SNAPSHOT CPUID=", (output / "stdout.log").read_text())
        self.assertIn("GS_SNAPSHOT DBGMCU_IDCODE=", (output / "stderr.log").read_text())
        session = (output / "session.tcl").read_text()
        for event in ("examine-end", "halted", "reset-init", "reset-end", "gdb-attach", "gdb-detach"):
            line = f"$_TARGETNAME configure -event {event} {{}}"
            self.assertIn(line, session)
            self.assertLess(session.index(line), session.index("\n    init\n"))
        self.assertNotRegex(session, r"(?m)^\s*(halt|reset|mww|mmw|write_memory|program|flash)\b")
        self.assertEqual(session.count("read_memory"), 5)

    def assert_failure(self, mode):
        process, result, _ = self.run_entry(mode)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["outcome"], "failed")
        self.assertTrue(result["error"])
        return result

    def test_missing_field_fails(self):
        self.assertFalse(self.assert_failure("missing")["readback_observed"])

    def test_duplicate_field_fails(self):
        self.assertFalse(self.assert_failure("duplicate")["readback_observed"])

    def test_read_error_fails(self):
        self.assertFalse(self.assert_failure("error")["readback_observed"])

    def test_nonzero_exit_fails(self):
        self.assertEqual(self.assert_failure("exit")["openocd_exit_code"], 5)

    def test_identity_mismatch_fails_but_retains_readback(self):
        result = self.assert_failure("identity")
        self.assertTrue(result["readback_observed"])
        self.assertFalse(result["identity_matches_expected"])

    def test_capacity_mismatch_fails(self):
        self.assertFalse(self.assert_failure("capacity")["identity_matches_expected"])

    def test_timeout_fails_and_preserves_partial_log(self):
        result = self.assert_failure("timeout")
        self.assertTrue(result["timed_out"])
        output = self.output / (self._testMethodName + " output with spaces")
        self.assertIn("MOCK: timeout", (output / "stdout.log").read_text())

    def test_serial_tcl_injection_rejected_before_process(self):
        process, result, _ = self.run_entry(extra=("-ProbeSerial", "x}; init; #"))
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)

    def test_readflash_offline_only_plans_dump(self):
        process, result, output = self.run_entry(execute=False, extra=("-ReadFlash",))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(result["hardware_contact_attempted"])
        self.assertTrue(result["flash_readback_requested"])
        self.assertFalse(result["flash_readback_complete"])
        self.assertIsNone(result["flash_readback"])
        self.assertEqual(result["planned_flash_readback"]["size_bytes"], 1048576)
        self.assertNotIn("dump_image", (output / "session.tcl").read_text())
        self.assertIn("dump_image target-flash.bin 0x08000000 0x00100000", (output / "read-plan.tcl").read_text())
        self.assertFalse((output / "target-flash.bin").exists())

    def test_readflash_complete_size_hash_and_guard_order(self):
        process, result, output = self.run_entry(extra=("-ReadFlash",))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(result["flash_readback_complete"])
        self.assertEqual(result["outcome"], "flash_readback_complete")
        raw = (output / "target-flash.bin").read_bytes()
        self.assertEqual(raw, bytes(range(256)) * 4096)
        self.assertEqual(result["flash_readback"]["size_bytes"], 1048576)
        self.assertEqual(result["flash_readback"]["sha256"], hashlib.sha256(raw).hexdigest())
        session = (output / "session.tcl").read_text()
        dump = session.index("dump_image target-flash.bin 0x08000000 0x00100000")
        self.assertLess(session.index("\n    init\n"), dump)
        self.assertLess(session.index("$cpuid != 0x410fc241"), dump)
        self.assertLess(session.index("[file exists target-flash.bin]"), dump)
        self.assertGreater(session.index("echo GS_SNAPSHOT_FLASH_COMPLETE"), dump)
        self.assertNotRegex(session, r"(?m)^\s*(halt|reset|mww|mmw|write_memory|program|flash)\b")

    def assert_flash_failure(self, mode):
        process, result, output = self.run_entry(mode, extra=("-ReadFlash",))
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["outcome"], "failed")
        self.assertFalse(result["flash_readback_complete"])
        self.assertIsNone(result["flash_readback"])
        self.assertTrue(result["error"])
        return result, output

    def test_readflash_truncated_fails(self):
        _, output = self.assert_flash_failure("flash_short")
        self.assertEqual((output / "target-flash.bin").stat().st_size, 1048320)

    def test_readflash_missing_marker_fails(self):
        _, output = self.assert_flash_failure("flash_no_marker")
        self.assertEqual((output / "target-flash.bin").stat().st_size, 1048576)

    def test_readflash_duplicate_marker_fails(self):
        self.assert_flash_failure("flash_duplicate_marker")

    def test_readflash_missing_file_fails(self):
        self.assert_flash_failure("flash_missing_file")

    def test_readflash_existing_file_rejected_before_process(self):
        process, result, output = self.run_entry(extra=("-ReadFlash",), existing_flash=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)
        self.assertEqual((output / "target-flash.bin").read_bytes(), b"old file must remain unchanged")
        self.assertFalse((output / "mock-started.txt").exists())

    def test_readflash_mismatches_do_not_enter_dump(self):
        for mode in ("identity", "capacity", "flash_cpuid"):
            with self.subTest(mode=mode):
                _, output = self.assert_flash_failure(mode)
                self.assertFalse((output / "target-flash.bin").exists())
                self.assertNotIn("MOCK: dump_image entered", (output / "stdout.log").read_text())

    def test_readflash_nonzero_exit_not_complete(self):
        result, _ = self.assert_flash_failure("flash_exit")
        self.assertEqual(result["openocd_exit_code"], 5)

    def test_readflash_timeout_even_after_marker_not_complete(self):
        result, output = self.assert_flash_failure("flash_timeout")
        self.assertTrue(result["timed_out"])
        self.assertIn("GS_SNAPSHOT_FLASH_COMPLETE", (output / "stdout.log").read_text())


if __name__ == "__main__":
    program = unittest.main(argv=[sys.argv[0]] + remaining, exit=False,
                            testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
    result = program.result
    summary_path = ROOT / "Build/agent-team/round5/executor/test-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(dict(
        timestamp_utc=datetime.now(timezone.utc).isoformat(), tests_run=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), successful=result.wasSuccessful(),
        synthetic_only=True, hardware_contacted=False,
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (ENTRY, Path(__file__), ROOT / "Tests/fixtures/snapshot_openocd_mock.c")}
    ), indent=2) + "\n", encoding="utf-8")
    sys.exit(0 if result.wasSuccessful() else 1)
