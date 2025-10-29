#!/usr/bin/env python3

import socket
import struct
import ctypes
import os
import subprocess
from pyroute2 import IPDB, NetNS

# --- Constants and Structures (omitted for brevity, same as before) ---
MRT_BASE = 200
MRT_INIT = MRT_BASE + 0
MRT_DONE = MRT_BASE + 1
MRT_ADD_VIF = MRT_BASE + 2
MRT_ADD_MFC = MRT_BASE + 4
MRT_DEL_MFC = MRT_BASE + 5
MAXVIFS = 32
IFF_MULTICAST = 0x1000

class Vifctl(ctypes.Structure):
    _fields_ = [
        ("vifc_vifi", ctypes.c_ushort),
        ("vifc_flags", ctypes.c_ubyte),
        ("vifc_threshold", ctypes.c_ubyte),
        ("vifc_rate_limit", ctypes.c_uint),
        ("vifc_lcl_addr", ctypes.c_uint),
        ("vifc_rmt_addr", ctypes.c_uint),
    ]

class Mfcctl(ctypes.Structure):
    _fields_ = [
        ("mfcc_origin", ctypes.c_uint),
        ("mfcc_mcastgrp", ctypes.c_uint),
        ("mfcc_parent", ctypes.c_ushort),
        ("mfcc_ttls", ctypes.c_ubyte * MAXVIFS),
    ]

def verify_mfc_entry(ns_name, source, group, iif, should_exist=True):
    """Verifies MFC entry by shelling out to 'ip mroute show'."""
    print(f"VERIFY: Checking if route ({source}, {group}) via {iif} {'exists' if should_exist else 'is deleted'}...")
    try:
        cmd = ["ip", "netns", "exec", ns_name, "ip", "mroute", "show"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = result.stdout
        expected_entry = f"({source}, {group}) Iif: {iif}"
        
        found = expected_entry in output
        
        if (found and should_exist) or (not found and not should_exist):
            print(f"VERIFY SUCCESS: Route found: {found}, as expected.")
            return True
        
        print(f"VERIFY FAILURE: Route found: {found}, but should exist: {should_exist}.")
        print(f"--- Full 'ip mroute show' in {ns_name} ---" + (output if output.strip() else "(empty)"))
        return False
    except Exception as e:
        print(f"VERIFY ERROR: Exception during verification: {e}")
        return False

def mfc_test_logic(ns_name, iif_name, iif_ip, oif_name, oif_ip):
    """The core MFC manipulation logic to be run inside the namespace."""
    sock = None
    try:
        print(f"\n--- Running test logic in namespace '{ns_name}' ---")
        
        SOURCE_IP = "192.168.1.100"
        GROUP_IP = "224.1.2.3"
        IIF_VIFI = 0
        OIF_VIFI = 1

        with NetNS(ns_name) as ns:
            print("--> Enabling MULTICAST flag on interfaces (natively)...")
            for if_name in [iif_name, oif_name]:
                with ns.get_links(ifname=if_name)[0] as link:
                    link.flags |= IFF_MULTICAST
                    link.commit()
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        
        print("--> Initializing Kernel Multicast Routing (MRT_INIT)...")
        sock.setsockopt(socket.IPPROTO_IP, MRT_INIT, 1)
        
        print(f"--> Adding VIFs...")
        vif_iif = Vifctl(vifc_vifi=IIF_VIFI, vifc_lcl_addr=struct.unpack("=I", socket.inet_aton(iif_ip))[0])
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_VIF, vif_iif)
        print(f"  - Added VIF {IIF_VIFI} for IIF {iif_name}")

        vif_oif = Vifctl(vifc_vifi=OIF_VIFI, vifc_lcl_addr=struct.unpack("=I", socket.inet_aton(oif_ip))[0])
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_VIF, vif_oif)
        print(f"  - Added VIF {OIF_VIFI} for OIF {oif_name}")
        
        print("--> Adding MFC entry...")
        mfc = Mfcctl(
            mfcc_origin=struct.unpack("=I", socket.inet_aton(SOURCE_IP))[0],
            mfcc_mcastgrp=struct.unpack("=I", socket.inet_aton(GROUP_IP))[0],
            mfcc_parent=IIF_VIFI,
        )
        mfc.mfcc_ttls[OIF_VIFI] = 1
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_MFC, mfc)
        
        if not verify_mfc_entry(ns_name, SOURCE_IP, GROUP_IP, iif_name, should_exist=True):
            raise RuntimeError("Verification failed after adding MFC entry.")
        
        print("--> Deleting MFC entry...")
        sock.setsockopt(socket.IPPROTO_IP, MRT_DEL_MFC, mfc)

        if not verify_mfc_entry(ns_name, SOURCE_IP, GROUP_IP, iif_name, should_exist=False):
            raise RuntimeError("Verification failed after deleting MFC entry.")

    finally:
        if sock:
            print("--> De-initializing Kernel Multicast Routing (MRT_DONE)...")
            sock.setsockopt(socket.IPPROTO_IP, MRT_DONE, 1)
            sock.close()

def main():
    NS_NAME = "mfc-test-ns"
    VETH_IIF_HOST = "veth-iif-h"
    VETH_IIF_NS = "veth-iif-ns"
    VETH_IIF_NS_IP = "192.168.200.2"
    VETH_OIF_HOST = "veth-oif-h"
    VETH_OIF_NS = "veth-oif-ns"
    VETH_OIF_NS_IP = "192.168.201.2"

    ipdb = IPDB()
    ns = None
    
    try:
        print(f"--- Setting up network namespace '{NS_NAME}' ---")
        # Create the namespace object first
        ns = NetNS(NS_NAME, flags=os.O_CREAT)

        # Create and configure IIF veth pair
        ipdb.create(kind='veth', ifname=VETH_IIF_HOST, peer=VETH_IIF_NS).commit()
        with ipdb.interfaces[VETH_IIF_HOST] as i:
            i.add_ip('192.168.200.1/24')
            i.up()
        # Correctly get the peer object and move it
        with ipdb.interfaces[VETH_IIF_NS] as peer:
            peer.net_ns_fd = NS_NAME

        # Create and configure OIF veth pair
        ipdb.create(kind='veth', ifname=VETH_OIF_HOST, peer=VETH_OIF_NS).commit()
        with ipdb.interfaces[VETH_OIF_HOST] as i:
            i.add_ip('192.168.201.1/24')
            i.up()
        # Correctly get the peer object and move it
        with ipdb.interfaces[VETH_OIF_NS] as peer:
            peer.net_ns_fd = NS_NAME
        
        # Configure interfaces inside the namespace
        with IPDB(nl=ns) as ipdb_ns:
            with ipdb_ns.interfaces[VETH_IIF_NS] as peer:
                peer.add_ip(f"{VETH_IIF_NS_IP}/24")
                peer.up()
            with ipdb_ns.interfaces[VETH_OIF_NS] as peer:
                peer.add_ip(f"{VETH_OIF_NS_IP}/24")
                peer.up()
            with ipdb_ns.interfaces.lo as lo:
                lo.up()

        # Run the test logic inside the fully configured namespace
        ns.run(mfc_test_logic, ns_name=NS_NAME, 
               iif_name=VETH_IIF_NS, iif_ip=VETH_IIF_NS_IP,
               oif_name=VETH_OIF_NS, oif_ip=VETH_OIF_NS_IP)
        
        print("\nSUCCESS: Test completed successfully.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED: {e}")
    finally:
        print("--- Cleaning up ---")
        if ipdb.interfaces.get(VETH_IIF_HOST):
            ipdb.interfaces[VETH_IIF_HOST].remove()
        if ipdb.interfaces.get(VETH_OIF_HOST):
            ipdb.interfaces[VETH_OIF_HOST].remove()
        if ns:
            ns.close()
        ipdb.release()

if __name__ == "__main__":
    main()
