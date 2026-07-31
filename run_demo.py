"""Manual demo runner: points app.py at the synthetic fixture log instead of
the real server_log.txt, so the whole pipeline can be checked without Dota
running. Not part of the plan's tasks - a convenience script for manual
testing only."""
import shutil

import config

config.SERVER_LOG_PATH = "/tmp/my_test_log.txt"
shutil.copy("fixtures/server_log_sample.txt", config.SERVER_LOG_PATH)

from app import OverlayApp

OverlayApp().run()
