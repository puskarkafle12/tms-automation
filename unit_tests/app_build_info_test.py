import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from config import app_build_info


class AppBuildInfoTest(unittest.TestCase):
    def setUp(self):
        app_build_info._DEPLOYED_AT_CACHE = None

    def test_prefers_app_build_date_env(self):
        with patch.dict(os.environ, {"APP_BUILD_DATE": "2026-03-18T10:15:00+00:00"}, clear=False):
            app_build_info._DEPLOYED_AT_CACHE = None
            deployed = app_build_info.get_deployed_at()
            self.assertEqual(deployed.isoformat(), "2026-03-18T10:15:00+00:00")

    def test_reads_deployed_at_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".deployed_at").write_text("2026-02-01T08:00:00+00:00", encoding="utf-8")
            env_clear = {
                "APP_DEPLOYED_AT": "",
                "APP_BUILD_DATE": "",
                "BUILD_DATE": "",
            }
            with patch.dict(os.environ, env_clear, clear=False):
                with patch.object(app_build_info, "_REPO_ROOT", root):
                    app_build_info._DEPLOYED_AT_CACHE = None
                    deployed = app_build_info.get_deployed_at()
                    self.assertEqual(deployed.isoformat(), "2026-02-01T08:00:00+00:00")

    def test_get_app_build_info_shape(self):
        with patch.dict(os.environ, {"APP_BUILD_DATE": "2026-01-01T00:00:00+00:00", "APP_GIT_COMMIT": "abc123"}, clear=False):
            app_build_info._DEPLOYED_AT_CACHE = None
            info = app_build_info.get_app_build_info()
            self.assertEqual(info["deployed_at"], "2026-01-01T00:00:00+00:00")
            self.assertEqual(info["git_commit"], "abc123")


if __name__ == "__main__":
    unittest.main()
