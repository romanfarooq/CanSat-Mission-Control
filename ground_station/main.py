"""CanSat Mission Control — run with --demo for synthetic, unlogged telemetry."""

import argparse
import tkinter as tk

from pathlib import Path

from mission_control import MissionControl


def main():
    """Parse command-line options and start the desktop event loop."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Synthetic preview, no CSV")
    parser.add_argument("--log-dir", type=Path, help="Live CSV output directory")
    args = parser.parse_args()
    root = tk.Tk()
    app = MissionControl(root, args.demo, args.log_dir)
    if args.demo:
        app.notice = "DEMO / synthetic values · CSV logging disabled"
    try:
        root.mainloop()
    except KeyboardInterrupt:
        # Keep Tk running until the serial and camera workers have closed.
        app.close()
        root.mainloop()


if __name__ == "__main__":
    main()
