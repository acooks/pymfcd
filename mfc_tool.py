#!/usr/bin/env python3

import socket
from pyroute2 import IPRoute

def get_if_name(ip, if_index):
    """Helper function to get interface name from index."""
    try:
        link_info = ip.get_links(if_index)
        if link_info:
            return link_info[0].get_attr('IFLA_IFNAME')
    except (IndexError, KeyError):
        pass
    return f"idx {if_index}"

def print_all_routes():
    """
    Connects to the kernel and dumps all routing table entries.
    This is a diagnostic step to verify basic pyroute2 functionality.
    """
    ip = IPRoute()
    try:
        print("Attempting to fetch all IPv4 routes...")
        routes = ip.get_routes(family=socket.AF_INET)

        if not routes:
            print("No IPv4 routes found.")
            return

        print("All Kernel IPv4 Routes:")
        print("---------------------------------------------------------------------")
        print(f"{'Type':<10} {'Source':<18} {'Destination':<18} {'Gateway':<18} {'OIF'}")
        print("---------------------------------------------------------------------")

        for entry in routes:
            attrs = dict(entry['attrs'])
            route_type = entry.get('type', 'N/A')
            source = attrs.get('RTA_SRC', '(*)')
            destination = attrs.get('RTA_DST', 'default')
            gateway = attrs.get('RTA_GATEWAY', 'N/A')
            oif_index = attrs.get('RTA_OIF', 0)
            oif_name = get_if_name(ip, oif_index) if oif_index else 'N/A'

            # Convert route_type integer to a more readable string if possible
            # pyroute2 often provides a 'type' field that maps to RTN_* enums
            type_name = str(route_type)
            if hasattr(ip.rtmsg, 'rtm_type') and route_type in ip.rtmsg.rtm_type.values():
                for name, val in ip.rtmsg.rtm_type.items():
                    if val == route_type:
                        type_name = name
                        break

            print(f"{type_name:<10} {source:<18} {destination:<18} {gateway:<18} {oif_name}")

        print("---------------------------------------------------------------------")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("Please ensure you have sufficient privileges (try running with sudo).")
    finally:
        ip.close()

if __name__ == "__main__":
    print_all_routes()
