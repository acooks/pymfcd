"""
mfc_daemon.py: A final diagnostic script to bypass the Python socket wrapper.

This script calls the C `setsockopt` function directly from libc to eliminate
the Python wrapper as a variable.
"""
import socket
import ctypes
import time
import signal
import sys

def main():
    # --- Kernel Constants and Structures ---
    MRT_INIT = 200
    MRT_ADD_VIF = 202
    MRT_ADD_MFC = 204
    MRT_DONE = 201
    IPPROTO_IP = 0
    MAXVIFS = 32
    VIFF_USE_IFINDEX = 0x8

    class _Vifctl_Lcl(ctypes.Union):
        _fields_ = [
            ("vifc_lcl_addr", ctypes.c_uint),
            ("vifc_lcl_ifindex", ctypes.c_int),
        ]

    class VirtualInterfaceControl(ctypes.Structure):
        _fields_ = [
            ("vifc_vifi", ctypes.c_ushort),
            ("vifc_flags", ctypes.c_ubyte),
            ("vifc_threshold", ctypes.c_ubyte),
            ("vifc_rate_limit", ctypes.c_uint),
            ("_lcl", _Vifctl_Lcl),
            ("vifc_rmt_addr", ctypes.c_uint),
        ]
        _anonymous_ = ("_lcl",)

    class MulticastForwardingCacheControl(ctypes.Structure):
        _fields_ = [
            ("mfcc_origin", ctypes.c_uint),
            ("mfcc_mcastgrp", ctypes.c_uint),
            ("mfcc_parent", ctypes.c_ushort),
            ("mfcc_ttls", ctypes.c_ubyte * MAXVIFS),
            ("_padding", ctypes.c_ubyte * 2),
            ("mfcc_pkt_cnt", ctypes.c_uint),
            ("mfcc_byte_cnt", ctypes.c_uint),
            ("mfcc_wrong_if", ctypes.c_uint),
            ("mfcc_expire", ctypes.c_int),
        ]

    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ifindex_in> <ifindex_out>", file=sys.stderr)
        sys.exit(1)

    ifindex_in = int(sys.argv[1])
    ifindex_out = int(sys.argv[2])

    sock = None
    try:
        # --- Load libc and define setsockopt function signature ---
        libc = ctypes.CDLL('libc.so.6', use_errno=True)
        c_setsockopt = libc.setsockopt
        c_setsockopt.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
        c_setsockopt.restype = ctypes.c_int

        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        
        # Use Python wrapper for simple calls
        sock.setsockopt(IPPROTO_IP, MRT_INIT, 1)

        # VIFs
        vif_in = VirtualInterfaceControl()
        vif_in.vifc_vifi = 0
        vif_in.vifc_flags = VIFF_USE_IFINDEX
        vif_in.vifc_lcl_ifindex = ifindex_in
        sock.setsockopt(IPPROTO_IP, MRT_ADD_VIF, vif_in)

        vif_out = VirtualInterfaceControl()
        vif_out.vifc_vifi = 1
        vif_out.vifc_flags = VIFF_USE_IFINDEX
        vif_out.vifc_lcl_ifindex = ifindex_out
        sock.setsockopt(IPPROTO_IP, MRT_ADD_VIF, vif_out)

        # MFC Entry
        mfc_entry = MulticastForwardingCacheControl()
        mfc_entry.mfcc_origin = int.from_bytes(socket.inet_aton("0.0.0.0"), 'big')
        mfc_entry.mfcc_mcastgrp = int.from_bytes(socket.inet_aton("239.1.2.3"), 'big')
        mfc_entry.mfcc_parent = 0
        mfc_entry.mfcc_ttls[1] = 1

        # --- Call C setsockopt directly ---
        print("\n[Daemon] Calling C setsockopt directly for MRT_ADD_MFC...")
        ret = c_setsockopt(sock.fileno(), IPPROTO_IP, MRT_ADD_MFC,
                           ctypes.byref(mfc_entry), ctypes.sizeof(mfc_entry))
        
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"C setsockopt failed with errno {errno}")

        print("\n[Daemon] SUCCESS: Multicast route configured. Running persistently.")
        while True:
            time.sleep(1)

    except OSError as e:
        print(f"\n[Daemon] An OSError occurred: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if sock:
            sock.setsockopt(IPPROTO_IP, MRT_DONE, 1)
            sock.close()

def handle_signal(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    main()