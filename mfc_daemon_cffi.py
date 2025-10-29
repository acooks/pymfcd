import time
import socket
import sys
import os
import signal
from cffi import FFI

# CFFI setup
ffi = FFI()

# Define the C source for cffi to compile. This includes the necessary
# headers and the structures we need. This is the key part that avoids
# the manual layout issues of ctypes.
C_HEADER_CODE = """
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <linux/mroute.h>

    int setsockopt(int sockfd, int level, int optname, const void *optval, socklen_t optlen);
"""
ffi.cdef(C_HEADER_CODE)

# Define constants in Python. We could parse them from headers, but this is simpler.
IPPROTO_IP = 0
IPPROTO_IGMP = 2
MRT_INIT = 200
MRT_DONE = 201
MRT_ADD_VIF = 202
MRT_ADD_MFC = 204


class MRouteDaemon:
    def __init__(self, ifindex_in, ifindex_out):
        self.ifindex_in = ifindex_in
        self.ifindex_out = ifindex_out
        self.sock = None
        # Load the C library
        self.libc = ffi.dlopen("c")

    def start(self):
        """Initializes the multicast engine and adds the route."""
        print("[CFFI Daemon] Starting...")
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, IPPROTO_IGMP)

            # MRT_INIT
            print("[CFFI Daemon] Calling MRT_INIT...")
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

            # Add VIFs
            print(f"[CFFI Daemon] Adding VIF 0 (ifindex {self.ifindex_in})...")
            vif_in = ffi.new("struct vifctl *")
            vif_in.vifc_vifi = 0
            vif_in.vifc_flags = ffi.cast("unsigned char", 0x8)  # VIFF_USE_IFINDEX
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

            print(f"[CFFI Daemon] Adding VIF 1 (ifindex {self.ifindex_out})...")
            vif_out = ffi.new("struct vifctl *")
            vif_out.vifc_vifi = 1
            vif_out.vifc_flags = ffi.cast("unsigned char", 0x8)  # VIFF_USE_IFINDEX
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

            # Add MFC entry
            print("[CFFI Daemon] Adding MFC entry for (*, 239.1.2.3)...")
            mfc = ffi.new("struct mfcctl *")
            mfc.mfcc_origin.s_addr = socket.inet_aton("0.0.0.0")[0]
            mfc.mfcc_mcastgrp.s_addr = socket.inet_aton("239.1.2.3")[0]
            mfc.mfcc_parent = 0  # VIF 0 is input
            mfc.mfcc_ttls[1] = 1  # VIF 1 is output with TTL 1
            self._check_call(
                self.libc.setsockopt(
                    self.sock.fileno(),
                    IPPROTO_IP,
                    MRT_ADD_MFC,
                    mfc,
                    ffi.sizeof("struct mfcctl"),
                )
            )

            print("[CFFI Daemon] SUCCESS: Route added. Running persistently.")

            # Keep the daemon alive
            while True:
                time.sleep(1)

        except Exception as e:
            print(f"[CFFI Daemon] ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    def stop(self):
        """Cleans up the multicast engine state."""
        if self.sock:
            print("\n[CFFI Daemon] Shutting down. Calling MRT_DONE...")
            done_val = ffi.new("int*", 1)
            # This might fail if the process is killed abruptly, but we try.
            self.libc.setsockopt(
                self.sock.fileno(), IPPROTO_IP, MRT_DONE, done_val, ffi.sizeof("int")
            )
            self.sock.close()
            print("[CFFI Daemon] Cleanup complete.")

    def _check_call(self, ret_code):
        """Checks the return code of a C call and raises an OSError if it failed."""
        if ret_code < 0:
            errno = ffi.errno
            raise OSError(errno, os.strerror(errno))


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ifindex_in> <ifindex_out>", file=sys.stderr)
        sys.exit(1)

    ifindex_in = int(sys.argv[1])
    ifindex_out = int(sys.argv[2])

    daemon = MRouteDaemon(ifindex_in, ifindex_out)

    def signal_handler(sig, frame):
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    daemon.start()


if __name__ == "__main__":
    main()
