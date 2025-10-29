#!/usr/bin/env python3

import socket
import struct
import ctypes
import os

# --- Constants from Kernel Headers ---
# /usr/include/linux/netlink.h
NLMSG_NOOP = 0x1
NLMSG_ERROR = 0x2
NLMSG_DONE = 0x3
NLMSG_OVERRUN = 0x4

NLM_F_REQUEST = 1
NLM_F_DUMP = 0x100 | 0x200  # NLM_F_ROOT | NLM_F_MATCH

# /usr/include/linux/rtnetlink.h
RTM_GETROUTE = 26
RTN_MULTICAST = 5

# /usr/include/bits/socket.h
AF_NETLINK = 16
AF_INET = 2

# /usr/include/linux/socket.h
NETLINK_ROUTE = 0

# rtattr types from rtnetlink.h
RTA_DST = 1
RTA_SRC = 2
RTA_IIF = 3
RTA_OIF = 4
RTA_GATEWAY = 5
RTA_MULTIPATH = 9
RTA_TABLE = 15
RTA_MFC_STATS = 17

# --- C Structures via ctypes ---
class Nlmsghdr(ctypes.Structure):
    _fields_ = [
        ("nlmsg_len", ctypes.c_uint32),
        ("nlmsg_type", ctypes.c_uint16),
        ("nlmsg_flags", ctypes.c_uint16),
        ("nlmsg_seq", ctypes.c_uint32),
        ("nlmsg_pid", ctypes.c_uint32),
    ]

    def __repr__(self):
        return (
            f"len={self.nlmsg_len}, type={self.nlmsg_type}, "
            f"flags={self.nlmsg_flags}, seq={self.nlmsg_seq}, "
            f"pid={self.nlmsg_pid}"
        )

class Rtmsg(ctypes.Structure):
    _fields_ = [
        ("rtm_family", ctypes.c_ubyte),
        ("rtm_dst_len", ctypes.c_ubyte),
        ("rtm_src_len", ctypes.c_ubyte),
        ("rtm_tos", ctypes.c_ubyte),
        ("rtm_table", ctypes.c_ubyte),
        ("rtm_protocol", ctypes.c_ubyte),
        ("rtm_scope", ctypes.c_ubyte),
        ("rtm_type", ctypes.c_ubyte),
        ("rtm_flags", ctypes.c_uint),
    ]

    def __repr__(self):
        return (
            f"family={self.rtm_family}, dst_len={self.rtm_dst_len}, "
            f"src_len={self.rtm_src_len}, type={self.rtm_type}, "
            f"table={self.rtm_table}"
        )

def parse_rtattr(data):
    """Parses a buffer of rtattr attributes into a dictionary."""
    attrs = {}
    while len(data) >= 4:
        try:
            rta_len, rta_type = struct.unpack("=HH", data[:4])
            if rta_len < 4:
                print(f"DEBUG: Invalid rta_len {rta_len}, breaking.")
                break

            payload = data[4:rta_len]
            
            if rta_type == RTA_DST:
                attrs['RTA_DST'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_SRC:
                attrs['RTA_SRC'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_IIF:
                attrs['RTA_IIF'] = struct.unpack("=i", payload)[0]
            elif rta_type == RTA_OIF:
                attrs['RTA_OIF'] = struct.unpack("=i", payload)[0]
            elif rta_type == RTA_GATEWAY:
                attrs['RTA_GATEWAY'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_TABLE:
                 attrs['RTA_TABLE'] = struct.unpack("=I", payload)[0]
            elif rta_type == RTA_MFC_STATS:
                # struct rta_mfc_stats { __u64 packets, __u64 bytes, __u64 wrong_if }
                stats = struct.unpack("=QQQ", payload)
                attrs['RTA_MFC_STATS'] = {'packets': stats[0], 'bytes': stats[1], 'wrong_if': stats[2]}
            else:
                attrs[f'RTA_UNKNOWN_{rta_type}'] = payload.hex()

            # Move to the next attribute
            rta_len_aligned = (rta_len + 3) & ~3
            data = data[rta_len_aligned:]
        except struct.error as e:
            print(f"DEBUG: Struct unpack error: {e}, remaining data: {data.hex()}")
            break
    return attrs

def main():
    sock = None
    try:
        # 1. Create and bind the Netlink socket
        print("DEBUG: Creating Netlink socket...")
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE)
        pid = os.getpid()
        sock.bind((pid, 0))
        print(f"DEBUG: Socket created and bound to PID {pid}.")

        # 2. Craft the request message
        seq = 12345
        nlmsghdr = Nlmsghdr(
            nlmsg_len=ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg),
            nlmsg_type=RTM_GETROUTE,
            nlmsg_flags=NLM_F_REQUEST | NLM_F_DUMP,
            nlmsg_seq=seq,
            nlmsg_pid=pid,
        )
        rtmsg = Rtmsg(rtm_family=AF_INET)
        request = bytes(nlmsghdr) + bytes(rtmsg)
        print(f"DEBUG: Sending request: Nlmsghdr({nlmsghdr}) Rtmsg({rtmsg})")
        print(f"DEBUG: Request buffer (hex): {request.hex()}")

        # 3. Send the request
        sock.send(request, 0)
        print("DEBUG: Request sent.")

        # 4. Receive the response
        mfc_entries = []
        print("DEBUG: Entering receive loop...")
        while True:
            data = sock.recv(65535)
            print(f"DEBUG: Received {len(data)} bytes from kernel.")
            
            offset = 0
            while offset < len(data):
                hdr = Nlmsghdr.from_buffer_copy(data[offset:])
                print(f"DEBUG: Parsing message at offset {offset}: Nlmsghdr({hdr})")

                if hdr.nlmsg_type == NLMSG_DONE:
                    print("DEBUG: Received NLMSG_DONE. End of dump.")
                    break
                if hdr.nlmsg_type == NLMSG_ERROR:
                    error_code = struct.unpack("=i", data[offset+ctypes.sizeof(Nlmsghdr):offset+ctypes.sizeof(Nlmsghdr)+4])[0]
                    print(f"DEBUG: Received NLMSG_ERROR. Code: {error_code} ({os.strerror(-error_code)})")
                    break
                
                msg_len = hdr.nlmsg_len
                if msg_len > len(data) - offset:
                    print(f"DEBUG: Incomplete message received (len={msg_len}, remaining={len(data)-offset}). Breaking.")
                    break
                
                msg_data = data[offset : offset + msg_len]
                
                rtmsg_offset = ctypes.sizeof(Nlmsghdr)
                rtm = Rtmsg.from_buffer_copy(msg_data[rtmsg_offset:])
                print(f"DEBUG:  - Rtmsg({rtm})")
                
                if rtm.rtm_type == RTN_MULTICAST:
                    print("DEBUG:  - Route type is RTN_MULTICAST. Parsing attributes.")
                    rtattr_offset = rtmsg_offset + ctypes.sizeof(Rtmsg)
                    attrs = parse_rtattr(msg_data[rtattr_offset:])
                    print(f"DEBUG:  - Parsed attributes: {attrs}")
                    mfc_entries.append(attrs)

                offset += msg_len
            
            if hdr.nlmsg_type == NLMSG_DONE or hdr.nlmsg_type == NLMSG_ERROR:
                break
        
        print("\n--- RESULTS ---")
        if not mfc_entries:
            print("Multicast Forwarding Cache is empty.")
            return

        print("Kernel Multicast Forwarding Cache (MFC):")
        for i, entry in enumerate(mfc_entries):
            print(f"Entry {i}: {entry}")

    except Exception as e:
        print(f"\n--- An error occurred ---")
        print(f"Error: {e}")
        print("Please ensure you have sufficient privileges (try running with sudo).")
    finally:
        if sock:
            sock.close()
            print("\nDEBUG: Socket closed.")

if __name__ == "__main__":
    main()
