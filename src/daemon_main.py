# src/daemon_main.py
import argparse
import os
import sys

from .config import load_config
from .mfc_daemon import MfcDaemon


def main():
    # Load configuration from file first
    config = load_config()

    parser = argparse.ArgumentParser(description="MFC Daemon Service")
    parser.add_argument(
        "--socket-path",
        default=config["socket_path"],
        help=f"Path to the Unix Domain Socket (default: {config['socket_path']})",
    )
    parser.add_argument(
        "--state-file",
        default=config["state_file"],
        help=f"Path to the state persistence file (default: {config['state_file']})",
    )
    args = parser.parse_args()

    # Ensure state directory exists
    state_dir = os.path.dirname(args.state_file)
    if state_dir and not os.path.exists(state_dir):
        os.makedirs(state_dir, exist_ok=True)

    daemon = MfcDaemon()
    # Pass the resolved config values to the entrypoint
    daemon.main_entrypoint(
        socket_path=args.socket_path,
        state_file_path=args.state_file,
        socket_group=config["socket_group"],
    )


if __name__ == "__main__":
    # Check for root privileges
    if os.geteuid() != 0:
        print("ERROR: MFC Daemon must be run with root privileges.", file=sys.stderr)
        sys.exit(1)
    main()
