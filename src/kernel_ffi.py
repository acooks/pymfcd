# src/kernel_ffi.py
import os
import socket

from cffi import FFI

# --- Python Constants ---
IPPROTO_IP = 0
IPPROTO_IGMP = 2
MRT_INIT = 200
MRT_DONE = 201
MRT_ADD_VIF = 202
MRT_DEL_VIF = 203
MRT_ADD_MFC = 204
MRT_DEL_MFC = 205
VIFF_USE_IFINDEX = 0x8


class KernelInterface:
    """
    A dedicated class to encapsulate all low-level interaction with the
    kernel's multicast routing API via CFFI. No application logic should
    reside here.
    """

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
            // CRITICAL: This padding is not visible in the C header,
            // but is added by the C compiler to align the next field on a
            // 4-byte boundary. We must replicate it exactly.
            char _padding[2];
            unsigned int mfcc_pkt_cnt;
            unsigned int mfcc_byte_cnt;
            unsigned int mfcc_wrong_if;
            int mfcc_expire;
        };

        // The function we need to call
        int setsockopt(int sockfd, int level, int optname, const void *optval,
                       socklen_t optlen);
    """

    def __init__(self):
        self.ffi = FFI()
        self.ffi.cdef(self.C_HEADER_CODE)
        self.libc = self.ffi.dlopen("c")
        self.sock = None

    def _check_call(self, description, ret_code):
        """Checks the return code of a C call and raises an OSError if it failed."""
        if ret_code < 0:
            errno = self.ffi.errno
            raise OSError(errno, f"[{description}] {os.strerror(errno)}")

    def mrt_init(self):
        """
        Opens the raw IGMP socket and initializes the kernel's multicast
        routing engine for this process.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, IPPROTO_IGMP)

        init_val = self.ffi.new("int*", 1)
        ret = self.libc.setsockopt(
            self.sock.fileno(),
            IPPROTO_IP,
            MRT_INIT,
            init_val,
            self.ffi.sizeof("int"),
        )
        self._check_call("MRT_INIT", ret)

    def mrt_done(self):
        """
        De-initializes the kernel's multicast routing engine and closes the socket.
        """
        if self.sock:
            try:
                done_val = self.ffi.new("int*", 1)
                ret = self.libc.setsockopt(
                    self.sock.fileno(),
                    IPPROTO_IP,
                    MRT_DONE,
                    done_val,
                    self.ffi.sizeof("int"),
                )
                self._check_call("MRT_DONE", ret)
            finally:
                self.sock.close()
                self.sock = None

    def _add_vif(self, vifi, ifindex):
        """
        Adds a VIF to the kernel multicast engine.

        :param vifi: The VIF index to assign.
        :param ifindex: The underlying physical interface index.
        """
        vif_ctl = self.ffi.new("struct vifctl *")
        vif_ctl.vifc_vifi = vifi
        vif_ctl.vifc_flags = VIFF_USE_IFINDEX
        vif_ctl.vifc_lcl_ifindex = ifindex

        ret = self.libc.setsockopt(
            self.sock.fileno(),
            IPPROTO_IP,
            MRT_ADD_VIF,
            vif_ctl,
            self.ffi.sizeof("struct vifctl"),
        )
        self._check_call(f"MRT_ADD_VIF for vifi {vifi}", ret)

    def _add_mfc(self, source_ip, group_ip, iif_vifi, oif_vifis):
        """
        Adds an MFC entry to the kernel.

        :param source_ip: The source IP address string.
        :param group_ip: The group IP address string.
        :param iif_vifi: The VIF index for the incoming interface.
        :param oif_vifis: A list of VIF indices for outgoing interfaces.
        """
        mfc_ctl = self.ffi.new("struct mfcctl *")

        # CRITICAL: Convert IPs to little-endian integers for CFFI
        mfc_ctl.mfcc_origin.s_addr = int.from_bytes(
            socket.inet_aton(source_ip), "little"
        )
        mfc_ctl.mfcc_mcastgrp.s_addr = int.from_bytes(
            socket.inet_aton(group_ip), "little"
        )

        mfc_ctl.mfcc_parent = iif_vifi

        # Set TTLs for output VIFs. A TTL of 1 is standard.
        for vifi in oif_vifis:
            if 0 <= vifi < 32:  # MAXVIFS
                mfc_ctl.mfcc_ttls[vifi] = 1

        ret = self.libc.setsockopt(
            self.sock.fileno(),
            IPPROTO_IP,
            MRT_ADD_MFC,
            mfc_ctl,
            self.ffi.sizeof("struct mfcctl"),
        )
        self._check_call(f"MRT_ADD_MFC for ({source_ip}, {group_ip})", ret)

    def _del_vif(self, vifi, ifindex):
        """
        Deletes a VIF from the kernel multicast engine.
        The kernel identifies the VIF to delete by its vifc_vifi and
        vifc_lcl_ifindex.
        """
        vif_ctl = self.ffi.new("struct vifctl *")
        vif_ctl.vifc_vifi = vifi
        vif_ctl.vifc_lcl_ifindex = ifindex

        ret = self.libc.setsockopt(
            self.sock.fileno(),
            IPPROTO_IP,
            MRT_DEL_VIF,
            vif_ctl,
            self.ffi.sizeof("struct vifctl"),
        )
        self._check_call(f"MRT_DEL_VIF for vifi {vifi}", ret)

    def _del_mfc(self, source_ip, group_ip):
        """
        Deletes an MFC entry from the kernel.
        The kernel identifies the MFC to delete by its origin and group.
        """
        mfc_ctl = self.ffi.new("struct mfcctl *")
        mfc_ctl.mfcc_origin.s_addr = int.from_bytes(
            socket.inet_aton(source_ip), "little"
        )
        mfc_ctl.mfcc_mcastgrp.s_addr = int.from_bytes(
            socket.inet_aton(group_ip), "little"
        )

        ret = self.libc.setsockopt(
            self.sock.fileno(),
            IPPROTO_IP,
            MRT_DEL_MFC,
            mfc_ctl,
            self.ffi.sizeof("struct mfcctl"),
        )
        self._check_call(f"MRT_DEL_MFC for ({source_ip}, {group_ip})", ret)
