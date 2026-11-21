r"""Set the admin PIN: writes its hash into config.toml.

    .venv\Scripts\python tools\set_pin.py           (asks for the PIN)
    .venv\Scripts\python tools\set_pin.py 123456    (PIN as argument)
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import ROOT, hash_pin  # noqa: E402


for _stream in (sys.stdout, sys.stderr):      # Windows consoles default to cp1252
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

def main() -> int:
    pin = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Neue Admin-PIN (4–8 Ziffern): ")
    if not re.fullmatch(r"\d{4,8}", pin):
        print("Die PIN muss aus 4 bis 8 Ziffern bestehen.")
        return 1
    path = ROOT / "config.toml"
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(r'(?m)^pin_sha256\s*=\s*".*"$', f'pin_sha256 = "{hash_pin(pin)}"', text)
    if count != 1:
        print("In config.toml wurde die Zeile pin_sha256 nicht gefunden.")
        return 1
    path.write_text(new_text, encoding="utf-8", newline="\n")
    print("PIN gespeichert. Bitte den Server neu starten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
