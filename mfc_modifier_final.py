#!/usr/bin/env python3

import socket
import struct
import ctypes
import os
import subprocess
from pyroute2 import IPDB
from pyroute2 import netns as pyroute2_netns

# --- Constants and Structures ---
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
    """Verifies MFC entry by shelling out to 'ip mroute show'."""
    print(f"VERIFY: Checking if route ({source}, {group}) via {iif} {'exists' if should_exist else 'is deleted'}...")
    try:
        # No 'ip netns exec' needed; we are already in the namespace
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

def run_mfc_test(iif_name, iif_ip, oif_name, oif_ip):
    """
    A self-contained function that performs the entire MFC test.
    It initializes the kernel, adds a route, verifies, deletes, verifies,
    and guarantees cleanup. Returns True on success, False on failure.
    This function runs *inside* the network namespace.
    """
    sock = None
    test_success = False
    try:
        print(f"\n--- Running MFC test logic in current namespace ---")
        
        SOURCE_IP = "192.168.1.100"
        GROUP_IP = "224.1.2.3"
        IIF_VIFI = 0
        OIF_VIFI = 1
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        
        # First, ensure the interfaces are up and have multicast enabled within this namespace
        # We need to create a new IPDB instance here that operates on the current namespace
        with IPDB() as ipdb_ns_local:
            for ifname in [iif_name, oif_name, "lo"]:
                try:
                    with ipdb_ns_local.interfaces[ifname] as link:
                        link.flags |= IFF_MULTICAST
                        link.up()
                        print(f"  - Configured {if_name} with MULTICAST flag and UP state.")
                except Exception as e:
                    print(f"ERROR: Could not configure interface {ifname} in namespace: {e}")
                    # This is critical, if setup fails, no point in continuing
                    return False

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
        
        if not verify_mfc_entry(None, SOURCE_IP, GROUP_IP, iif_name, should_exist=True):
            return False
        
        print("--> Deleting MFC entry...")
        sock.setsockopt(socket.IPPROTO_IP, MRT_DEL_MFC, mfc)

        if not verify_mfc_entry(None, SOURCE_IP, GROUP_IP, iif_name, should_exist=False):
            return False
        
        test_success = True
        return True

    except Exception as e:
        print(f"ERROR: MFC test logic failed: {e}")
        return False
    finally:
        if sock:
            print("--> De-initializing Kernel Multicast Routing (MRT_DONE)...")
            sock.setsockopt(socket.IPPROTO_IP, MRT_DONE, 1)
            sock.close()
            print("--> MFC test logic finished.")

def main():
    NS_NAME = "mfc-test-ns"
    VETH_IIF_HOST = "veth-iif-h"
    VETH_IIF_NS = "veth-iif-ns"
    VETH_IIF_NS_IP = "192.168.200.2"
    VETH_OIF_HOST = "veth-oif-h"
    VETH_OIF_NS = "veth-oif-ns"
    VETH_OIF_NS_IP = "192.168.201.2"

    ipdb_root = IPDB()
    
    try:
        print(f"--- Setting up network namespace '{NS_NAME}' ---")
        pyroute2_netns.create(NS_NAME)
        
        # Create and configure veth pairs in the root namespace
        # Then move the namespace-side peers into the new namespace
        with ipdb_root.create(kind='veth', ifname=VETH_IIF_HOST, peer=VETH_IIF_NS) as i:
            i.add_ip('192.168.200.1/24')
            i.up()
            i.peer.net_ns_fd = NS_NAME
            print(f"  - Created {VETH_IIF_HOST} (root) and moved {VETH_IIF_NS} to {NS_NAME}")

        with ipdb_root.create(kind='veth', ifname=VETH_OIF_HOST, peer=VETH_OIF_NS) as i:
            i.add_ip('192.168.201.1/24')
            i.up()
            i.peer.net_ns_fd = NS_NAME
            print(f"  - Created {VETH_OIF_HOST} (root) and moved {VETH_OIF_NS} to {NS_NAME}")

        # Configure interfaces inside the namespace (from the root, operating on the namespace)
        with IPDB(netns=NS_NAME) as ipdb_ns:
            print("--- Configuring interfaces inside namespace ---")
            for name, ip in [
                (VETH_IIF_NS, VETH_IIF_NS_IP),
                (VETH_OIF_NS, VETH_OIF_NS_IP),
                ("lo", "127.0.0.1")
            ]:
                try:
                    with ipdb_ns.interfaces[name] as current_iface:
                        if name != "lo": # loopback IP handled separately for consistency
                            current_iface.add_ip(f"{ip}/24")
                        current_iface.up()
                        # Note: Multicast flag will be set by run_mfc_test after pushns
                        print(f"  - Configured {name}")
                except Exception as e:
                    print(f"ERROR: Could not configure {name} in namespace: {e}")
                    raise # Re-raise to ensure cleanup

        # --- Test Execution Phase (running directly in the namespace) ---
        test_passed = False
        pyroute2_netns.pushns(NS_NAME)
        try:
            test_passed = run_mfc_test(
                iif_name=VETH_IIF_NS, iif_ip=VETH_IIF_NS_IP,
                oif_name=VETH_OIF_NS, oif_ip=VETH_OIF_NS_IP
            )
        except Exception as e:
            print(f"ERROR: Exception during run_mfc_test: {e}")
            test_passed = False
        finally:
            # CRITICAL: Always switch back to the root namespace
            pyroute2_netns.popns()
        
        if test_passed:
            print("\nSUCCESS: Test completed successfully.")
        else:
            print("\nFAILURE: Test failed.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED: {e}")
    finally:
        # --- Cleanup Phase (in root namespace) ---
        print("--- Cleaning up network resources ---")
        # IPDB automatically cleans up interfaces created by it
        # We need to manually delete the namespace first for clean IPDB cleanup
        if NS_NAME in pyroute2_netns.listnetns():
            pyroute2_netns.remove(NS_NAME)
            print(f"  - Namespace {NS_NAME} removed.")
        # Then release the IPDB, which will clean up veth pairs
        ipdb_root.release()
        print("--- Cleanup complete ---")

if __name__ == "__main__":
    main()