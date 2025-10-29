#!/usr/bin/env python3

import socket
import struct
import ctypes
import os
import json

# --- Constants from Kernel Headers ---
NLMSG_ERROR = 0x2
NLMSG_DONE = 0x3
NLM_F_REQUEST = 1
NLM_F_DUMP = 0x100 | 0x200
RTM_GETROUTE = 26
AF_NETLINK = 16
AF_INET = 2
NETLINK_ROUTE = 0

# rtattr types
RTA_DST = 1
RTA_OIF = 4
RTA_GATEWAY = 5
RTA_TABLE = 15

# rtm_type enum
RTN_UNICAST = 1
RTN_LOCAL = 2
RTN_BROADCAST = 3
RTN_MULTICAST = 5

# --- C Structures via ctypes ---
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

def get_if_name(if_index):
    """Helper to get interface name from index using a simple cache."""
    if if_index not in get_if_name.cache:
        try:
            get_if_name.cache[if_index] = socket.if_indextoname(if_index)
        except OSError:
            get_if_name.cache[if_index] = f"idx {if_index}"
    return get_if_name.cache[if_index]
get_if_name.cache = {}

def parse_rtattr(data):
    """Parses a buffer of rtattr attributes into a dictionary."""
    attrs = {}
    while len(data) >= 4:
        try:
            rta_len, rta_type = struct.unpack("=HH", data[:4])
            if rta_len < 4: break
            payload = data[4:rta_len]
            
            if rta_type == RTA_DST:
                attrs['dst'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_OIF:
                attrs['oif'] = get_if_name(struct.unpack("=i", payload)[0])
            elif rta_type == RTA_GATEWAY:
                attrs['gateway'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_TABLE:
                attrs['table'] = struct.unpack("=I", payload)[0]

            data = data[(rta_len + 3) & ~3:]
        except struct.error:
            break
    return attrs

def main():
    all_routes = []
    sock = None
    try:
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE)
        sock.bind((os.getpid(), 0))

        nlmsghdr = Nlmsghdr(
            nlmsg_len=ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg),
            nlmsg_type=RTM_GETROUTE,
            nlmsg_flags=NLM_F_REQUEST | NLM_F_DUMP,
            nlmsg_seq=1,
            nlmsg_pid=os.getpid(),
        )
        rtmsg = Rtmsg(rtm_family=AF_INET)
        sock.send(bytes(nlmsghdr) + bytes(rtmsg), 0)

        while True:
            data = sock.recv(65535)
            offset = 0
            while offset < len(data):
                hdr = Nlmsghdr.from_buffer_copy(data[offset:])
                if hdr.nlmsg_type == NLMSG_DONE: break
                if hdr.nlmsg_type == NLMSG_ERROR:
                    errno = -struct.unpack("=i", data[offset+ctypes.sizeof(Nlmsghdr):offset+ctypes.sizeof(Nlmsghdr)+4])[0]
                    print(f"Netlink error received: {os.strerror(errno)}")
                    break

                rtm = Rtmsg.from_buffer_copy(data[offset + ctypes.sizeof(Nlmsghdr):])
                route_info = {
                    'type': rtm.rtm_type,
                    'table': rtm.rtm_table,
                    'proto': rtm.rtm_protocol,
                    'scope': rtm.rtm_scope,
                }
                
                rtattr_data = data[offset + ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg):]
                attrs = parse_rtattr(rtattr_data)
                route_info.update(attrs)
                
                if 'dst' not in route_info:
                    route_info['dst'] = 'default' if rtm.rtm_dst_len == 0 else f'unknown/{rtm.rtm_dst_len}'
                else:
                    route_info['dst'] += f'/{rtm.rtm_dst_len}'

                all_routes.append(route_info)
                offset += hdr.nlmsg_len
            
            if hdr.nlmsg_type == NLMSG_DONE or hdr.nlmsg_type == NLMSG_ERROR:
                break
        
        print("--- Routes Parsed by ctypes Script ---")
        print(json.dumps(all_routes, indent=2))

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if sock:
            sock.close()

if __name__ == "__main__":
    main()
