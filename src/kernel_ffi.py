# src/kernel_ffi.py
import os
import socket

from cffi import FFI

# --- C-level Constants for setsockopt ---
# These constants are defined in the Linux kernel headers and are used to
# interact with the IP_MROUTE_SO socket options.
# Source: <uapi/linux/in.h>
IPPROTO_IP = 0  # Dummy protocol for setsockopt.
IPPROTO_IGMP = 2  # Protocol number for IGMP.

# Source: <uapi/linux/mroute.h>
MRT_INIT = 200  # Activate the multicast routing engine.
MRT_DONE = 201  # Deactivate the multicast routing engine.
MRT_ADD_VIF = 202  # Add a virtual interface (VIF).
MRT_DEL_VIF = 203  # Delete a virtual interface.
MRT_ADD_MFC = 204  # Add a multicast forwarding cache entry.
MRT_DEL_MFC = 205  # Delete a multicast forwarding cache entry.

# VIF flags. Source: <uapi/linux/mroute.h>
VIFF_USE_IFINDEX = 0x8  # VIF is identified by ifindex, not IP address.


class KernelInterface:
    """
    A dedicated class to encapsulate all low-level interaction with the
    kernel's multicast routing API via CFFI.

    This class acts as a Foreign Function Interface (FFI) to the kernel's
    multicast routing functionality, which is normally only accessible from C.
    It uses `setsockopt` on a raw IGMP socket to pass C structures to the
    kernel, effectively acting as an ioctl-like interface.

    No application logic should reside here. This class is solely responsible
    for translating Python data into the required C structures and making the
    necessary kernel calls.
    """

    # The C source code is a minimal subset of kernel headers required for
    # multicast routing control. This avoids needing the actual kernel headers
    # to be present on the system at compile time.
    # Source: <uapi/linux/in.h> and <uapi/linux/mroute.h>
    C_HEADER_CODE = """
        // Basic types from the kernel headers
        typedef unsigned short vifi_t;
        typedef unsigned int socklen_t;

        struct in_addr {
            unsigned int s_addr; // IP address in network byte order
        };

        // Copied from <uapi/linux/mroute.h>
        #define MAXVIFS 32

        /*
         * The vifctl struct is used to add or delete a Virtual Interface (VIF)
         * from the kernel's multicast routing table. A VIF represents either
         * a physical interface or a tunnel that can forward multicast traffic.
         */
        struct vifctl {
            vifi_t vifc_vifi;           // Index of the VIF you are adding/deleting.
            unsigned char vifc_flags;   // VIFF_* flags. We use VIFF_USE_IFINDEX.
            unsigned char vifc_threshold; // Min TTL required for a packet to be forwarded.
            unsigned int vifc_rate_limit; // Rate limit (currently unused by kernel).
            union {
                // Local IP address of the VIF (if not using ifindex).
                struct in_addr vifc_lcl_addr;
                int vifc_lcl_ifindex;         // The ifindex of the underlying interface.
            };
            struct in_addr vifc_rmt_addr; // Remote IP for tunnels (unused by us).
        };

        /*
         * The mfcctl struct is used to add or delete a Multicast Forwarding Cache
         * (MFC) entry. An MFC entry is the core multicast routing rule that tells
         * the kernel how to forward a packet for a specific (Source, Group) pair.
         */
        struct mfcctl {
            struct in_addr mfcc_origin;    // Source IP address of the multicast stream.
            struct in_addr mfcc_mcastgrp;  // Multicast group IP address.
            vifi_t mfcc_parent;            // VIF index of the incoming interface (IIF).
            // TTL threshold for each outgoing VIF (OIF).
            // A value > 0 means forward on that VIF.
            unsigned char mfcc_ttls[MAXVIFS];
            // CRITICAL: This padding is not visible in the C header,
            // but is added by the C compiler to align the next field on a
            // 4-byte boundary. We must replicate it exactly.
            char _padding[2];
            unsigned int mfcc_pkt_cnt;     // Kernel-maintained packet count (output only).
            unsigned int mfcc_byte_cnt;    // Kernel-maintained byte count (output only).
            unsigned int mfcc_wrong_if;    // Kernel-maintained wrong IIF count (output only).
            int mfcc_expire;               // Kernel-maintained expiry timer (output only).
        };

        // The libc function we need to call for all kernel interactions.
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
        routing engine for this process by calling MRT_INIT.

        This must be the first call made. It tells the kernel that this
        process will be responsible for managing multicast routing. Only one
        process can do this at a time.
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
        De-initializes the kernel's multicast routing engine by calling
        MRT_DONE and closes the socket.

        This should be called on graceful shutdown to clean up kernel resources.
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
        Adds a VIF to the kernel multicast engine using MRT_ADD_VIF.

        :param vifi: The VIF index (0-31) to assign to this interface.
        :param ifindex: The underlying physical interface index from the kernel.
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
        Adds an MFC entry to the kernel using MRT_ADD_MFC.

        :param source_ip: The source IP address string (e.g., "192.168.1.10").
        :param group_ip: The group IP address string (e.g., "239.1.2.3").
        :param iif_vifi: The VIF index for the incoming interface (the "parent").
        :param oif_vifis: A list of VIF indices for outgoing interfaces.
        """
        mfc_ctl = self.ffi.new("struct mfcctl *")

        # Convert Python IP strings to network-byte-order integers for the C struct.
        mfc_ctl.mfcc_origin.s_addr = int.from_bytes(
            socket.inet_aton(source_ip), "little"
        )
        mfc_ctl.mfcc_mcastgrp.s_addr = int.from_bytes(
            socket.inet_aton(group_ip), "little"
        )

        mfc_ctl.mfcc_parent = iif_vifi

        # Set TTLs for output VIFs. A TTL value > 0 in a VIF's position in
        # the array tells the kernel to forward packets to that VIF. A value
        # of 1 is standard, meaning the TTL is not decremented on forward.
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
        Deletes a VIF from the kernel multicast engine using MRT_DEL_VIF.
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
        Deletes an MFC entry from the kernel using MRT_DEL_MFC.
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
