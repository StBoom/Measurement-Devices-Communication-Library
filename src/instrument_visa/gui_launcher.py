from __future__ import annotations

import traceback
from pathlib import Path
from tkinter import messagebox

from instrument_visa.gui import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        error_text = traceback.format_exc()
        Path("startup_error.log").write_text(error_text, encoding="utf-8")
        messagebox.showerror("Instrument VISA Export", f"Startfehler: {exc}\n\nDetails: startup_error.log")
        raise
