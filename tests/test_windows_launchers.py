import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherTests(unittest.TestCase):
    def test_start_launcher_rejects_a_reused_unrelated_pid(self):
        launcher = (ROOT / "Start SKATE.bat").read_text(encoding="utf-8")
        self.assertIn("serverProcess.Path", launcher)
        self.assertIn("SKATE_PYTHON", launcher)
        self.assertIn("<title>SKATE", launcher)
        self.assertIn('del /q "%SKATE_PID_FILE%"', launcher)

    def test_stop_launcher_removes_the_default_server_pid_file(self):
        launcher = (ROOT / "Stop SKATE.bat").read_text(encoding="utf-8")
        self.assertIn('set "SKATE_PID_FILE=%SKATE_ROOT%.skate-server.pid"', launcher)
        self.assertIn('if "%%Q"=="8765"', launcher)
        self.assertIn('del /q "%SKATE_PID_FILE%"', launcher)

    def test_installer_uses_pinned_reusable_whisper_models(self):
        build_script = (ROOT / "build-app.ps1").read_text(encoding="utf-8")
        self.assertIn('build\\model-cache\\whisper', build_script)
        self.assertIn('d90ca5fe260221311c53c58e660288d3deb8d356', build_script)
        self.assertIn('ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66', build_script)
        self.assertIn('Invoke-WebRequest -UseBasicParsing', build_script)
        self.assertIn("Whisper models validated.", build_script)


if __name__ == "__main__":
    unittest.main()
