#!/usr/bin/env python3

import os
import sys
from pyroute2 import IPDB
from pyroute2.netns import NSPopen
import subprocess

def main():
    NS_NAME = "mfc-test-ns"
    VETH_IIF_HOST = "veth-iif-h"
    VETH_IIF_NS = "veth-iif-ns"
    VETH_IIF_NS_IP = "192.168.200.2"
    VETH_OIF_HOST = "veth-oif-h"
    VETH_OIF_NS = "veth-oif-ns"
    VETH_OIF_NS_IP = "192.168.201.2"

    ipdb = IPDB()
    
    try:
        print(f"--- Setting up network namespace '{NS_NAME}' ---")
        # Create the namespace using the command-line tool, as it's simpler
        subprocess.run(["ip", "netns", "add", NS_NAME], check=True)

        # Create and configure IIF veth pair
        ipdb.create(kind='veth', ifname=VETH_IIF_HOST, peer=VETH_IIF_NS).commit()
        with ipdb.interfaces[VETH_IIF_HOST] as i:
            i.add_ip('192.168.200.1/24')
            i.up()
        with ipdb.interfaces[VETH_IIF_NS] as peer:
            peer.net_ns_fd = NS_NAME

        # Create and configure OIF veth pair
        ipdb.create(kind='veth', ifname=VETH_OIF_HOST, peer=VETH_OIF_NS).commit()
        with ipdb.interfaces[VETH_OIF_HOST] as i:
            i.add_ip('192.168.201.1/24')
            i.up()
        with ipdb.interfaces[VETH_OIF_NS] as peer:
            peer.net_ns_fd = NS_NAME
        
        # Configure interfaces inside the namespace using 'ip netns exec'
        subprocess.run(["ip", "netns", "exec", NS_NAME, "ip", "addr", "add", f"{VETH_IIF_NS_IP}/24", "dev", VETH_IIF_NS], check=True)
        subprocess.run(["ip", "netns", "exec", NS_NAME, "ip", "link", "set", "dev", VETH_IIF_NS, "up"], check=True)
        subprocess.run(["ip", "netns", "exec", NS_NAME, "ip", "addr", "add", f"{VETH_OIF_NS_IP}/24", "dev", VETH_OIF_NS], check=True)
        subprocess.run(["ip", "netns", "exec", NS_NAME, "ip", "link", "set", "dev", VETH_OIF_NS, "up"], check=True)
        subprocess.run(["ip", "netns", "exec", NS_NAME, "ip", "link", "set", "dev", "lo", "up"], check=True)

        print(f"\n--- Executing logic script in namespace '{NS_NAME}' ---")
        # Use NSPopen to run the logic script within the namespace
        cmd = [
            sys.executable, 
            "mfc_logic.py", 
            VETH_IIF_NS, 
            VETH_IIF_NS_IP, 
            VETH_OIF_NS, 
            VETH_OIF_NS_IP
        ]
        with NSPopen(NS_NAME, cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as p:
            for line in p.stdout:
                print(line.decode().strip())
        
        if p.returncode == 0:
            print("\nSUCCESS: Test completed successfully.")
        else:
            print(f"\nFAILURE: Test script exited with code {p.returncode}.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED: {e}")
    finally:
        print("--- Cleaning up ---")
        if os.path.exists(f"/var/run/netns/{NS_NAME}"):
            subprocess.run(["ip", "netns", "del", NS_NAME], check=False)
        if ipdb.interfaces.get(VETH_IIF_HOST):
            ipdb.interfaces[VETH_IIF_HOST].remove()
        if ipdb.interfaces.get(VETH_OIF_HOST):
            ipdb.interfaces[VETH_OIF_HOST].remove()
        ipdb.release()

if __name__ == "__main__":
    main()
