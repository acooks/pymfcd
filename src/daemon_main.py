# src/daemon_main.py
import sys
import os
import argparse
from .mfc_daemon import MfcDaemon

# Default paths (will be configurable via config file later)
DEFAULT_SOCKET_PATH = "/var/run/mfc_daemon.sock"
DEFAULT_STATE_FILE = "/var/lib/mfc_daemon/state.json"

def main():
    parser = argparse.ArgumentParser(description="MFC Daemon Service")
    parser.add_argument(
        "--socket-path",
        default=DEFAULT_SOCKET_PATH,
        help=f"Path to the Unix Domain Socket (default: {DEFAULT_SOCKET_PATH})",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help=f"Path to the state persistence file (default: {DEFAULT_STATE_FILE})",
    )
    args = parser.parse_args()

    # Ensure state directory exists
    state_dir = os.path.dirname(args.state_file)
    if state_dir and not os.path.exists(state_dir):
        os.makedirs(state_dir, exist_ok=True)

    daemon = MfcDaemon()
    daemon.main_entrypoint(args.socket_path, args.state_file)

if __name__ == "__main__":
    # Check for root privileges
    if os.geteuid() != 0:
        print("ERROR: MFC Daemon must be run with root privileges.", file=sys.stderr)
        sys.exit(1)
    main()
