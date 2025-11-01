# src/mfc_cli.py
import argparse
import json
import sys

from .common import send_ipc_command
from .daemon_main import DEFAULT_SOCKET_PATH


def main():
    parser = argparse.ArgumentParser(description="MFC CLI Client")
    parser.add_argument(
        "--socket-path",
        default=DEFAULT_SOCKET_PATH,
        help=(
            f"Path to the daemon's Unix Domain Socket (default: {DEFAULT_SOCKET_PATH})"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- 'mfc' command ---
    mfc_parser = subparsers.add_parser("mfc", help="Manage MFC rules")
    mfc_subparsers = mfc_parser.add_subparsers(dest="mfc_action", required=True)

    # 'mfc add'
    add_parser = mfc_subparsers.add_parser("add", help="Add an MFC rule")
    add_parser.add_argument("--source", default="0.0.0.0", help="Source IP address")
    add_parser.add_argument("--group", required=True, help="Multicast group IP address")
    add_parser.add_argument("--iif", required=True, help="Incoming interface name")
    add_parser.add_argument(
        "--oifs", required=True, help="Comma-separated list of outgoing interfaces"
    )

    # 'mfc del'
    del_parser = mfc_subparsers.add_parser("del", help="Delete an MFC rule")
    del_parser.add_argument("--source", default="0.0.0.0", help="Source IP address")
    del_parser.add_argument("--group", required=True, help="Multicast group IP address")

    # --- 'show' command ---
    subparsers.add_parser("show", help="Show current state")

    args = parser.parse_args()

    command = {}
    if args.command == "mfc":
        if args.mfc_action == "add":
            command = {
                "action": "ADD_MFC",
                "payload": {
                    "source": args.source,
                    "group": args.group,
                    "iif": args.iif,
                    "oifs": args.oifs.split(","),
                },
            }
        elif args.mfc_action == "del":
            command = {
                "action": "DEL_MFC",
                "payload": {
                    "source": args.source,
                    "group": args.group,
                },
            }
    elif args.command == "show":
        command = {"action": "SHOW"}

    try:
        response = send_ipc_command(args.socket_path, command)
        print(json.dumps(response, indent=2))
    except ConnectionRefusedError:
        print(
            f"Error: Connection to daemon at {args.socket_path} refused. "
            "Is it running?",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
