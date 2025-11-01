# src/mfc_cli.py
import argparse
import json
import sys

from .common import send_ipc_command
from .config import load_config


def _print_show_output(response):
    """Formats and prints the output of the 'show' command."""
    payload = response.get("payload", {})
    vif_map = payload.get("vif_map", {})
    mfc_rules = payload.get("mfc_rules", [])

    # --- Print VIF Table ---
    print("Virtual Interface Table (VIFs)")
    if not vif_map:
        print("  No VIFs configured.")
    else:
        print(f"{'VIF':<5} {'Interface':<15} {'Index':<10} {'Ref Count':<10}")
        print("-" * 45)
        for if_name, data in vif_map.items():
            print(
                f"{data['vifi']:<5} {if_name:<15} {data['ifindex']:<10} "
                f"{data['ref_count']:<10}"
            )

    print("\nMulticast Forwarding Cache (MFC)")
    if not mfc_rules:
        print("  No MFC rules installed.")
    else:
        print(f"{'Source':<18} {'Group':<18} {'IIF':<15} {'OIFs'}")
        print("-" * 70)
        for rule in mfc_rules:
            oifs_str = ", ".join(rule["oifs"])
            print(
                f"{rule['source']:<18} {rule['group']:<18} {rule['iif']:<15} {oifs_str}"
            )


def main():
    config = load_config()
    parser = argparse.ArgumentParser(description="MFC CLI Client")
    parser.add_argument(
        "--socket-path",
        default=config["socket_path"],
        help=(
            "Path to the daemon's Unix Domain Socket "
            f"(default from config: {config['socket_path']})"
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
    show_parser = subparsers.add_parser("show", help="Show current state")
    show_parser.add_argument(
        "--json", action="store_true", help="Output raw JSON instead of formatted tables"
    )

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
        if args.command == "show" and response.get("status") == "success" and not args.json:
            _print_show_output(response)
        else:
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


if __name__ == "__main__":
    main()
