import struct
import time
import socket
import sys
import os
import signal
from cffi import FFI

# --- CFFI Setup ---
# This part is the core of the technical solution.
# It provides the C-level definitions directly to CFFI, avoiding
# the need for a preprocessor, which cdef does not support.
C_HEADER_CODE = """
    // Basic types from the kernel headers
    typedef unsigned short vifi_t;
    typedef unsigned int socklen_t;
    
    struct in_addr {
        unsigned int s_addr;
    };

    // Copied from <linux/mroute.h>
    #define MAXVIFS 32

    struct vifctl {
        vifi_t vifc_vifi;
        unsigned char vifc_flags;
        unsigned char vifc_threshold;
        unsigned int vifc_rate_limit;
        union {
            struct in_addr vifc_lcl_addr;
            int vifc_lcl_ifindex;
        };
        struct in_addr vifc_rmt_addr;
    };

    struct mfcctl {
        struct in_addr mfcc_origin;
        struct in_addr mfcc_mcastgrp;
        vifi_t mfcc_parent;
        unsigned char mfcc_ttls[MAXVIFS];
        char _padding[2]; // <--- CRITICAL FIX: Align next field to 4-byte boundary
        unsigned int mfcc_pkt_cnt;
        unsigned int mfcc_byte_cnt;
        unsigned int mfcc_wrong_if;
        int mfcc_expire;
    };

    // The function we need to call
    int setsockopt(int sockfd, int level, int optname, const void *optval, socklen_t optlen);
"""
ffi = FFI()
ffi.cdef(C_HEADER_CODE)

# --- Python Constants ---
IPPROTO_IP = 0
IPPROTO_IGMP = 2
MRT_INIT = 200
MRT_DONE = 201
MRT_ADD_VIF = 202
MRT_ADD_MFC = 204
VIFF_USE_IFINDEX = 0x8


class MRouteDaemon:
    def __init__(self, ifindex_in, ifindex_out):
        self.ifindex_in = ifindex_in
        self.ifindex_out = ifindex_out
        self.sock = None
        self.libc = ffi.dlopen("c")
        self.pid = os.getpid()

    def log(self, message):
        """Helper for logging with a clear prefix."""
        print(f"[Daemon PID:{self.pid}] {message}", flush=True)

    def start(self):
        """Initializes the multicast engine and adds the route."""
        self.log("Starting...")
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, IPPROTO_IGMP)

            # MRT_INIT
            self.log("ACTION: Calling setsockopt(MRT_INIT)...")
            init_val = ffi.new("int*", 1)
            self._check_call(
                self.libc.setsockopt(
                    self.sock.fileno(),
                    IPPROTO_IP,
                    MRT_INIT,
                    init_val,
                    ffi.sizeof("int"),
                )
            )
            self.log("...MRT_INIT successful.")

            # Add VIFs
            self.log(
                f"ACTION: Calling setsockopt(MRT_ADD_VIF) for VIF 0 (ifindex {self.ifindex_in})..."
            )
            vif_in = ffi.new("struct vifctl *")
            vif_in.vifc_vifi = 0
            vif_in.vifc_flags = VIFF_USE_IFINDEX
            vif_in.vifc_lcl_ifindex = self.ifindex_in
            self._check_call(
                self.libc.setsockopt(
                    self.sock.fileno(),
                    IPPROTO_IP,
                    MRT_ADD_VIF,
                    vif_in,
                    ffi.sizeof("struct vifctl"),
                )
            )
            self.log("...VIF 0 added.")

            self.log(
                f"ACTION: Calling setsockopt(MRT_ADD_VIF) for VIF 1 (ifindex {self.ifindex_out})..."
            )
            vif_out = ffi.new("struct vifctl *")
            vif_out.vifc_vifi = 1
            vif_out.vifc_flags = VIFF_USE_IFINDEX
            vif_out.vifc_lcl_ifindex = self.ifindex_out
            self._check_call(
                self.libc.setsockopt(
                    self.sock.fileno(),
                    IPPROTO_IP,
                    MRT_ADD_VIF,
                    vif_out,
                    ffi.sizeof("struct vifctl"),
                )
            )
            self.log("...VIF 1 added.")

            # Add MFC entry
            self.log("ACTION: Calling setsockopt(MRT_ADD_MFC) for (*, 239.1.2.3)...")
            mfc = ffi.new("struct mfcctl *")  # mfc is a POINTER, consistent with vifctl

            # Assign values to the struct's members via the pointer
            # CRITICAL FIX: We create a LITTLE-ENDIAN integer, because CFFI will
            # write it to memory using the host's byte order (little-endian),
            # which results in the correct BIG-ENDIAN byte layout that the kernel expects.
            mfc.mfcc_origin.s_addr = int.from_bytes(
                socket.inet_aton("0.0.0.0"), "little"
            )
            mfc.mfcc_mcastgrp.s_addr = int.from_bytes(
                socket.inet_aton("239.1.2.3"), "little"
            )

            mfc.mfcc_parent = 0
            mfc.mfcc_ttls[1] = 1

            # For debugging, dereference the pointer to inspect the struct's data
            self.log(f"MFC struct bytes (hex): {bytes(ffi.buffer(mfc)).hex()}")
            self.log(f"MFC struct size: {ffi.sizeof(mfc[0])}")

            self._check_call(
                self.libc.setsockopt(
                    self.sock.fileno(),
                    IPPROTO_IP,
                    MRT_ADD_MFC,
                    mfc,  # Pass the pointer directly, same as for vifctl
                    ffi.sizeof("struct mfcctl"),  # Pass the size of the struct type
                )
            )

            self.log(">>> SUCCESS: Setup complete. Running persistently. <<<")
            while True:
                time.sleep(1)

        except Exception as e:
            self.log(f"FATAL ERROR: {e}")
            sys.exit(1)

    def stop(self):
        if self.sock:
            self.log("Shutdown signal received.")
            self.log("ACTION: Calling setsockopt(MRT_DONE)...")
            done_val = ffi.new("int*", 1)
            self.libc.setsockopt(
                self.sock.fileno(), IPPROTO_IP, MRT_DONE, done_val, ffi.sizeof("int")
            )
            self.sock.close()
            self.log("...Cleanup complete.")

    def _check_call(self, ret_code):
        if ret_code < 0:
            errno = ffi.errno
            raise OSError(errno, os.strerror(errno))


def main():
    if len(sys.argv) != 3:
        print(
            f"[Daemon] Usage: {sys.argv[0]} <ifindex_in> <ifindex_out>", file=sys.stderr
        )
        sys.exit(1)

    daemon = MRouteDaemon(int(sys.argv[1]), int(sys.argv[2]))

    def signal_handler(sig, frame):
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    daemon.start()


if __name__ == "__main__":
    main()
