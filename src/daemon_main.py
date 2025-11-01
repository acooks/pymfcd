# src/daemon_main.py
import os
import sys

from .mfc_daemon import MfcDaemon


def main():
    # Ensure state directory exists (using default from config for now)
    # This will be refined when config is fully integrated
    state_dir = "/var/lib/mfc_daemon"
    if state_dir and not os.path.exists(state_dir):
        os.makedirs(state_dir, exist_ok=True)

    daemon = MfcDaemon()
    daemon.main_entrypoint(
        socket_path=os.environ.get("MFC_SOCKET_PATH"),
        state_file_path=os.environ.get("MFC_STATE_FILE"),
        socket_group=os.environ.get("MFC_SOCKET_GROUP"),
    )


if __name__ == "__main__":
    # Check for root privileges
    if os.geteuid() != 0:
        print("ERROR: MFC Daemon must be run with root privileges.", file=sys.stderr)
        sys.exit(1)
    main()
