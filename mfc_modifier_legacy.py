#!/usr/bin/env python3

import socket
import struct
import ctypes
import os
import subprocess
import time
import fcntl

# --- Constants from /usr/include/linux/mroute.h ---
MRT_BASE = 200
MRT_INIT = MRT_BASE + 0
MRT_DONE = MRT_BASE + 1
MRT_ADD_VIF = MRT_BASE + 2
MRT_DEL_VIF = MRT_BASE + 3
MRT_ADD_MFC = MRT_BASE + 4
MRT_DEL_MFC = MRT_BASE + 5

MAXVIFS = 32

# --- C Structures via ctypes ---
class Vifctl(ctypes.Structure):
    _fields_ = [
        ("vifc_vifi", ctypes.c_ushort),
        ("vifc_flags", ctypes.c_ubyte),
        ("vifc_threshold", ctypes.c_ubyte),
        ("vifc_rate_limit", ctypes.c_uint),
        ("vifc_lcl_addr", ctypes.c_uint), # in_addr
        ("vifc_rmt_addr", ctypes.c_uint), # in_addr
    ]

class Mfcctl(ctypes.Structure):
    _fields_ = [
        ("mfcc_origin", ctypes.c_uint), # in_addr
        ("mfcc_mcastgrp", ctypes.c_uint), # in_addr
        ("mfcc_parent", ctypes.c_ushort),
        ("mfcc_ttls", ctypes.c_ubyte * MAXVIFS),
    ]

# --- Helper Functions ---
def get_if_ip(if_name):
    """Retrieves the primary IPv4 address of an interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # SIOCGIFADDR is the ioctl for getting interface address
        # struct ifreq { char ifr_name[IFNAMSIZ]; struct sockaddr ifr_addr; ... }
        # IFNAMSIZ is 16
        ifreq = struct.pack('<16sH2s4s8s', if_name.encode('utf-8'), socket.AF_INET, b'', b'', b'')
        result = fcntl.ioctl(s.fileno(), 0x8915, ifreq) # SIOCGIFADDR
        ip_addr_packed = result[20:24] # struct sockaddr_in sa_data is 14 bytes, ip is at offset 20
        return socket.inet_ntoa(ip_addr_packed)
    except Exception as e:
        print(f"ERROR: Could not get IP address for interface '{if_name}': {e}")
        exit(1)
    finally:
        s.close()

def run_command(command, check=True):
    """Helper to run a shell command and print its output."""
    print(f"RUNNING: {' '.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=check)
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        return result.returncode == 0
    except Exception as e:
        print(f"ERROR: Failed to run command '{' '.join(command)}': {e}")
        return False

def verify_mfc_entry(source, group, iif, should_exist=True):
    """Verifies the existence or absence of an MFC entry using 'ip mroute show'."""
    print(f"VERIFY: Checking if route ({source}, {group}) via {iif} {'exists' if should_exist else 'is deleted'}...")
    try:
        result = subprocess.run(["ip", "mroute", "show"], capture_output=True, text=True, check=False)
        output = result.stdout
        expected_entry_part1 = f"({source}, {group})"
        expected_entry_part2 = f"Iif: {iif}"
        
        found = any(expected_entry_part1 in line and expected_entry_part2 in line for line in output.splitlines())
        
        if (found and should_exist) or (not found and not should_exist):
            print(f"VERIFY SUCCESS: Route found: {found}, as expected.")
            return True
        
        print(f"VERIFY FAILURE: Route found: {found}, but should exist: {should_exist}.")
        print("--- Full 'ip mroute show' output ---" + (output if output.strip() else "(empty)"))
        return False
    except Exception as e:
        print(f"VERIFY ERROR: Exception while running 'ip mroute show': {e}")
        return False

def main():
    IIF_NAME = "lo"
    OIF_NAME = "lo"
    SOURCE_IP = "192.168.1.100"
    GROUP_IP = "224.1.2.3"

    IIF_VIFI, OIF_VIFI = 0, 1

    sock = None
    try:
        print("--- Step 1: Enabling MULTICAST flag on interfaces ---")
        if not run_command(["ip", "link", "set", "dev", IIF_NAME, "multicast", "on"]): return
        if IIF_NAME != OIF_NAME and not run_command(["ip", "link", "set", "dev", OIF_NAME, "multicast", "on"]): return
        print("-" * 30)

        print("--- Step 2: Retrieving interface IP addresses ---")
        iif_ip = get_if_ip(IIF_NAME)
        oif_ip = get_if_ip(OIF_NAME)
        print(f"IIF ({IIF_NAME}) IP: {iif_ip}")
        print(f"OIF ({OIF_NAME}) IP: {oif_ip}")
        print("-" * 30)

        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        
        print("--- Step 3: Initializing Kernel Multicast Routing (MRT_INIT) ---")
        sock.setsockopt(socket.IPPROTO_IP, MRT_INIT, 1)
        print("SUCCESS: MRT_INIT called.")
        print("-" * 30)

        print(f"--- Step 4: Adding VIFs ---")
        vif_iif = Vifctl(vifc_vifi=IIF_VIFI, vifc_lcl_addr=struct.unpack("=I", socket.inet_aton(iif_ip))[0])
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_VIF, vif_iif)
        print(f"SUCCESS: Added VIF {IIF_VIFI} for IIF {IIF_NAME} (IP: {iif_ip})")
        
        vif_oif = Vifctl(vifc_vifi=OIF_VIFI, vifc_lcl_addr=struct.unpack("=I", socket.inet_aton(oif_ip))[0])
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_VIF, vif_oif)
        print(f"SUCCESS: Added VIF {OIF_VIFI} for OIF {OIF_NAME} (IP: {oif_ip})")
        print("-" * 30)

        print(f"--- Step 5: Adding MFC entry ---")
        mfc = Mfcctl(
            mfcc_origin=struct.unpack("=I", socket.inet_aton(SOURCE_IP))[0],
            mfcc_mcastgrp=struct.unpack("=I", socket.inet_aton(GROUP_IP))[0],
            mfcc_parent=IIF_VIFI,
        )
        mfc.mfcc_ttls[OIF_VIFI] = 1
        sock.setsockopt(socket.IPPROTO_IP, MRT_ADD_MFC, mfc)
        print("SUCCESS: MRT_ADD_MFC called.")
        
        if not verify_mfc_entry(SOURCE_IP, GROUP_IP, IIF_NAME, should_exist=True): return
        print("-" * 30)

        print(f"--- Step 6: Deleting MFC entry ---")
        sock.setsockopt(socket.IPPROTO_IP, MRT_DEL_MFC, mfc)
        print("SUCCESS: MRT_DEL_MFC called.")

        if not verify_mfc_entry(SOURCE_IP, GROUP_IP, IIF_NAME, should_exist=False): return
        print("-" * 30)

    except Exception as e:
        print(f"\nAN ERROR OCCURRED: {e}")
        print("This may require 'sudo' and for multicast routing to be enabled in the kernel.")
    finally:
        if sock:
            print("--- Step 7: De-initializing Kernel Multicast Routing (MRT_DONE) ---")
            sock.setsockopt(socket.IPPROTO_IP, MRT_DONE, 1)
            sock.close()
            print("SUCCESS: MRT_DONE called and socket closed.")

if __name__ == "__main__":
    main()