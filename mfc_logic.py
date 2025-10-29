#!/usr/bin/env python3

import socket
import struct
import ctypes
import os
import sys
import subprocess

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

def verify_mfc_entry(source, group, iif, should_exist=True):
    """Verifies MFC entry existence using 'ip mroute show'."""
    print(f"VERIFY: Checking if route ({source}, {group}) via {iif} {'exists' if should_exist else 'is deleted'}...")
    try:
        # We are already inside the namespace, so no 'ip netns exec' needed
        cmd = ["ip", "mroute", "show"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = result.stdout
        expected_entry = f"({source}, {group}) Iif: {iif}"
        
        found = expected_entry in output
        
        if (found and should_exist) or (not found and not should_exist):
            print(f"VERIFY SUCCESS: Route found: {found}, as expected.")
            return True
        
        print(f"VERIFY FAILURE: Route found: {found}, but should exist: {should_exist}.")
        print(f"--- Full 'ip mroute show' ---\n" + (output if output.strip() else "(empty)"))
        return False
    except Exception as e:
        print(f"VERIFY ERROR: Exception during verification: {e}")
        return False

def main(iif_name, iif_ip, oif_name, oif_ip):
    """The core MFC manipulation logic to be run inside the namespace."""
    sock = None
    try:
        print(f"\n--- Running test logic ---")
        
        SOURCE_IP = "192.168.1.100"
        GROUP_IP = "224.1.2.3"
        IIF_VIFI = 0
        OIF_VIFI = 1

        # Use subprocess to set multicast flag, as pyroute2 is not in this context
        subprocess.run(["ip", "link", "set", "dev", iif_name, "multicast", "on"], check=True)
        subprocess.run(["ip", "link", "set", "dev", oif_name, "multicast", "on"], check=True)
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        
        print("--> Initializing Kernel Multicast Routing (MRT_INIT)...")
        sock.setsockopt(socket.IPPROTO_IP, MRT_INIT, 1)
        
        print(f"--> Adding VIFs...")
        vif_iif = Vifctl(vifc_vifi=IIF_VIFI, vifc_lcl_addr=struct.unpack("=I", socket.inet_aton(iif_ip))[0])
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_VIF, vif_iif)
        vif_oif = Vifctl(vifc_vifi=OIF_VIFI, vifc_lcl_addr=struct.unpack("=I", socket.inet_aton(oif_ip))[0])
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_VIF, vif_oif)
        
        print("--> Adding MFC entry...")
        mfc = Mfcctl(
            mfcc_origin=struct.unpack("=I", socket.inet_aton(SOURCE_IP))[0],
            mfcc_mcastgrp=struct.unpack("=I", socket.inet_aton(GROUP_IP))[0],
            mfcc_parent=IIF_VIFI,
        )
        mfc.mfcc_ttls[OIF_VIFI] = 1
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_MFC, mfc)
        
        if not verify_mfc_entry(SOURCE_IP, GROUP_IP, iif_name, should_exist=True):
            sys.exit(1)
        
        print("--> Deleting MFC entry...")
        sock.setsockopt(socket.IPPROTO_IP, MRT_DEL_MFC, mfc)

        if not verify_mfc_entry(SOURCE_IP, GROUP_IP, iif_name, should_exist=False):
            sys.exit(1)

    finally:
        if sock:
            print("--> De-initializing Kernel Multicast Routing (MRT_DONE)...")
            sock.setsockopt(socket.IPPROTO_IP, MRT_DONE, 1)
            sock.close()

if __name__ == "__main__":
    # Get arguments from the command line
    if len(sys.argv) != 5:
        print("Usage: python3 mfc_logic.py <iif_name> <iif_ip> <oif_name> <oif_ip>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
