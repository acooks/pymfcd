#!/usr/bin/env python3

import socket
import struct
import ctypes

# Constants from /usr/include/linux/netlink.h and rtnetlink.h
NLMSG_NOOP = 0x1
NLMSG_ERROR = 0x2
NLMSG_DONE = 0x3
NLMSG_OVERRUN = 0x4

NLM_F_REQUEST = 1
NLM_F_DUMP = 0x100 | 0x200 # NLM_F_ROOT | NLM_F_MATCH

RTM_GETROUTE = 26
RTN_MULTICAST = 5

AF_NETLINK = 16
NETLINK_ROUTE = 0

# C Structures defined with ctypes
class Nlmsghdr(ctypes.Structure):
    _fields_ = [
        ("nlmsg_len", ctypes.c_uint32),
        ("nlmsg_type", ctypes.c_uint16),
        ("nlmsg_flags", ctypes.c_uint16),
        ("nlmsg_seq", ctypes.c_uint32),
        ("nlmsg_pid", ctypes.c_uint32),
    ]

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

def parse_rtattr(data):
    attrs = {}
    while len(data) > 0:
        try:
            rta_len, rta_type = struct.unpack("HH", data[:4])
            if rta_len < 4:
                break
            
            payload = data[4:rta_len]
            
            # Align to 4 bytes
            rta_len = (rta_len + 3) & ~3
            data = data[rta_len:]

            # From /usr/include/linux/rtnetlink.h -> enum rtattr_type_t
            RTA_DST = 1
            RTA_SRC = 2
            RTA_IIF = 3
            RTA_OIF = 4
            RTA_MULTIPATH = 9

            if rta_type == RTA_DST:
                attrs['RTA_DST'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_SRC:
                attrs['RTA_SRC'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_IIF:
                attrs['RTA_IIF'] = struct.unpack("i", payload)[0]
            elif rta_type == RTA_OIF:
                attrs['RTA_OIF'] = struct.unpack("i", payload)[0]
            elif rta_type == RTA_MULTIPATH:
                # For simplicity, we won't parse the complex multipath struct here
                attrs['RTA_MULTIPATH'] = True

        except struct.error:
            break
    return attrs

def main():
    try:
        # 1. Create the Netlink socket
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, socket.NETLINK_ROUTE)
        sock.bind((0, 0)) # Bind to own PID and group 0

        # 2. Craft the request message
        nlmsghdr = Nlmsghdr(
            nlmsg_len=ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg),
            nlmsg_type=RTM_GETROUTE,
            nlmsg_flags=NLM_F_REQUEST | NLM_F_DUMP,
            nlmsg_seq=1,
            nlmsg_pid=0, # Kernel
        )
        rtmsg = Rtmsg(rtm_family=socket.AF_INET)
        
        request = bytes(nlmsghdr) + bytes(rtmsg)

        # 3. Send the request
        sock.send(request, 0)

        # 4. Receive the response
        mfc_entries = []
        while True:
            data = sock.recv(65535)
            offset = 0
            while offset < len(data):
                hdr = Nlmsghdr.from_buffer_copy(data[offset:])
                if hdr.nlmsg_type == NLMSG_DONE:
                    break
                if hdr.nlmsg_type == NLMSG_ERROR:
                    print("Netlink error received.")
                    break

                msg_len = hdr.nlmsg_len
                msg_data = data[offset : offset + msg_len]
                
                # Parse the rtmsg and attributes
                rtmsg_offset = ctypes.sizeof(Nlmsghdr)
                rtm = Rtmsg.from_buffer_copy(msg_data[rtmsg_offset:])
                
                if rtm.rtm_type == RTN_MULTICAST:
                    rtattr_offset = rtmsg_offset + ctypes.sizeof(Rtmsg)
                    attrs = parse_rtattr(msg_data[rtattr_offset:])
                    mfc_entries.append(attrs)

                offset += msg_len
            
            if hdr.nlmsg_type == NLMSG_DONE or hdr.nlmsg_type == NLMSG_ERROR:
                break

        # 5. Print the results
        if not mfc_entries:
            print("Multicast Forwarding Cache is empty.")
            return

        print("Kernel Multicast Forwarding Cache (MFC):")
        print("---------------------------------------------------------------------")
        print(f"{'Source':<18} {'Group':<18} {'IIF':<10} {'OIFs'}")
        print("---------------------------------------------------------------------")

        for entry in mfc_entries:
            source = entry.get('RTA_SRC', '(*)')
            group = entry.get('RTA_DST', 'N/A')
            iif = entry.get('RTA_IIF', 'N/A')
            oif = entry.get('RTA_OIF', 'N/A')
            if entry.get('RTA_MULTIPATH'):
                oif = "MULTIPATH"

            print(f"{source:<18} {group:<18} {iif:<10} {oif}")

        print("---------------------------------------------------------------------")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("Please ensure you have sufficient privileges (try running with sudo).")
    finally:
        if 'sock' in locals():
            sock.close()

if __name__ == "__main__":
    main()
