"""Tralala serverini başladır: python main.py"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import uvicorn  # noqa: E402

from app.server import PORT, app, lan_ip  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"\n  Tralala hazırdır\n  Aparıcı paneli : http://localhost:{PORT}/admin"
          f"\n  Oyunçular      : http://{lan_ip()}:{PORT}\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
