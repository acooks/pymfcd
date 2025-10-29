#!/usr/bin/env python3

import socket
import struct
import ctypes
import os
import time

# --- Constants ---
NLMSG_ERROR = 0x2
NLMSG_DONE = 0x3
NLM_F_REQUEST = 1
NLM_F_DUMP = 0x100 | 0x200
NLM_F_CREATE = 0x400
NLM_F_REPLACE = 0x100
NLM_F_ACK = 4

RTM_NEWROUTE = 24
RTM_DELROUTE = 25
RTM_GETROUTE = 26

RTN_MULTICAST = 5
AF_NETLINK = 16
AF_INET = 2
NETLINK_ROUTE = 0

RTA_DST = 1
RTA_SRC = 2
RTA_IIF = 3
RTA_OIF = 4 # Still defined, but will be replaced by RTA_MULTIPATH for MFC
RTA_MULTIPATH = 9

# --- C Structures ---
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

class Rtnexthop(ctypes.Structure):
    _fields_ = [
        ("rtnh_len", ctypes.c_uint16),
        ("rtnh_flags", ctypes.c_ubyte),
        ("rtnh_hops", ctypes.c_ubyte),
        ("rtnh_ifindex", ctypes.c_int),
    ]

# --- Helper Functions ---
def get_if_index(if_name):
    try:
        return socket.if_nametoindex(if_name)
    except OSError:
        print(f"Error: Interface '{if_name}' not found.")
        exit(1)

def pack_rtattr(rta_type, payload):
    rta_len = 4 + len(payload)
    return struct.pack("=HH", rta_len, rta_type) + payload

def parse_rtattr(data):
    attrs = {}
    while len(data) >= 4:
        try:
            rta_len, rta_type = struct.unpack("=HH", data[:4])
            if rta_len < 4: break
            payload = data[4:rta_len]
            
            if rta_type == RTA_DST:
                attrs['RTA_DST'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_SRC:
                attrs['RTA_SRC'] = socket.inet_ntoa(payload)
            elif rta_type == RTA_IIF:
                attrs['RTA_IIF'] = struct.unpack("=i", payload)[0]
            elif rta_type == RTA_OIF:
                attrs['RTA_OIF'] = struct.unpack("=i", payload)[0]
            elif rta_type == RTA_MULTIPATH:
                # For simplicity, just indicate presence of multipath
                attrs['RTA_MULTIPATH'] = True

            data = data[(rta_len + 3) & ~3:]
        except struct.error:
            break
    return attrs

def get_mfc_routes(sock):
    pid = os.getpid()
    seq = int(time.time())
    
    nlmsghdr = Nlmsghdr(
        nlmsg_len=ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg),
        nlmsg_type=RTM_GETROUTE,
        nlmsg_flags=NLM_F_REQUEST | NLM_F_DUMP,
        nlmsg_seq=seq,
        nlmsg_pid=pid,
    )
    rtmsg = Rtmsg(rtm_family=AF_INET)
    sock.send(bytes(nlmsghdr) + bytes(rtmsg), 0)

    mfc_entries = []
    while True:
        data = sock.recv(65535)
        offset = 0
        while offset < len(data):
            hdr = Nlmsghdr.from_buffer_copy(data[offset:])
            if hdr.nlmsg_seq != seq:
                offset += hdr.nlmsg_len
                continue
            if hdr.nlmsg_type == NLMSG_DONE: break
            if hdr.nlmsg_type == NLMSG_ERROR: break

            rtm = Rtmsg.from_buffer_copy(data[offset + ctypes.sizeof(Nlmsghdr):])
            if rtm.rtm_type == RTN_MULTICAST:
                rtattr_data = data[offset + ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg):]
                attrs = parse_rtattr(rtattr_data)
                mfc_entries.append(attrs)
            offset += hdr.nlmsg_len
        if hdr.nlmsg_type == NLMSG_DONE or hdr.nlmsg_type == NLMSG_ERROR:
            break
    return mfc_entries

def send_request_and_check_ack(sock, request):
    sock.send(request, 0)
    while True:
        data = sock.recv(4096)
        hdr = Nlmsghdr.from_buffer_copy(data)
        if hdr.nlmsg_type == NLMSG_ERROR:
            payload_len = hdr.nlmsg_len - ctypes.sizeof(Nlmsghdr)
            if payload_len >= 4:
                errno = -struct.unpack("=i", data[ctypes.sizeof(Nlmsghdr):ctypes.sizeof(Nlmsghdr)+4])[0]
                return errno
            else:
                return -1
        if hdr.nlmsg_type != NLMSG_ERROR:
            continue

def run_ip_mroute_show():
    print("\n--- Output of 'sudo ip mroute show' ---")
    try:
        import subprocess
        result = subprocess.run(["sudo", "ip", "mroute", "show"], capture_output=True, text=True, check=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error executing 'sudo ip mroute show': {e}")
        print(f"Stderr: {e.stderr}")
    except FileNotFoundError:
        print("'ip' command not found. Please ensure iproute2 is installed.")
    print("--------------------------------------")

# --- Main Logic ---
def main():
    IIF_NAME = "lo"
    OIF_NAME = "lo"
    SOURCE_IP = "192.168.1.100"
    GROUP_IP = "224.1.2.3"

    iif_index = get_if_index(IIF_NAME)
    oif_index = get_if_index(OIF_NAME)

    sock = None
    try:
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE)
        sock.bind((os.getpid(), 0))

        print("--- Step 0: Verifying initial state ---")
        initial_routes = get_mfc_routes(sock)
        print(f"Found {len(initial_routes)} multicast routes initially:")
        for route in initial_routes:
            print(f"  - {route}")
        run_ip_mroute_show()
        print("-" * 30)

        print(f"--- Step 1: Adding/Replacing route: ({SOURCE_IP}, {GROUP_IP}) IIF:{IIF_NAME} OIF:{OIF_NAME} ---")
        attrs = bytearray()
        attrs.extend(pack_rtattr(RTA_SRC, socket.inet_aton(SOURCE_IP)))
        attrs.extend(pack_rtattr(RTA_DST, socket.inet_aton(GROUP_IP)))
        attrs.extend(pack_rtattr(RTA_IIF, struct.pack("=i", iif_index)))
        
        # Construct RTA_MULTIPATH for outgoing interfaces
        multipath_payload = bytearray()
        nh = Rtnexthop(
            rtnh_len=ctypes.sizeof(Rtnexthop),
            rtnh_flags=0,
            rtnh_hops=0,
            rtnh_ifindex=oif_index
        )
        multipath_payload.extend(bytes(nh))
        attrs.extend(pack_rtattr(RTA_MULTIPATH, multipath_payload))

        rtmsg = Rtmsg(rtm_family=AF_INET, rtm_src_len=32, rtm_dst_len=32, rtm_table=254, rtm_protocol=4, rtm_scope=0, rtm_type=RTN_MULTICAST)
        nlmsghdr = Nlmsghdr(
            nlmsg_len=ctypes.sizeof(Nlmsghdr) + ctypes.sizeof(Rtmsg) + len(attrs),
            nlmsg_type=RTM_NEWROUTE,
            nlmsg_flags=NLM_F_REQUEST | NLM_F_CREATE | NLM_F_REPLACE | NLM_F_ACK,
            nlmsg_seq=int(time.time()),
            nlmsg_pid=os.getpid(),
        )
        
        errno = send_request_and_check_ack(sock, bytes(nlmsghdr) + bytes(rtmsg) + attrs)
        if errno == 0: print("SUCCESS: Route added/replaced successfully (ACK received).")
        else:
            print(f"ERROR: Could not add/replace route: {os.strerror(errno)}")
            return
        print("-" * 30)

        print("--- Step 2: Verifying addition/replacement ---")
        routes_after_add = get_mfc_routes(sock)
        print(f"Found {len(routes_after_add)} multicast routes after add/replace.")
        if len(routes_after_add) >= len(initial_routes):
            print("SUCCESS: Route addition/replacement verified.")
        else:
            print("FAILURE: Route was not added/replaced.")
        run_ip_mroute_show()
        print("-" * 30)

        print(f"--- Step 3: Deleting route: ({SOURCE_IP}, {GROUP_IP}) ---")
        nlmsghdr.nlmsg_type = RTM_DELROUTE
        nlmsghdr.nlmsg_seq += 1
        
        errno = send_request_and_check_ack(sock, bytes(nlmsghdr) + bytes(rtmsg) + attrs)
        if errno == 0: print("SUCCESS: Route deleted successfully (ACK received).")
        else:
            print(f"ERROR: Could not delete route: {os.strerror(errno)}")
            return
        print("-" * 30)

        print("--- Step 4: Verifying deletion ---")
        routes_after_del = get_mfc_routes(sock)
        print(f"Found {len(routes_after_del)} multicast routes after delete.")
        if len(routes_after_del) < len(routes_after_add):
            print("SUCCESS: Route deletion verified.")
        else:
            print("FAILURE: Route was not deleted.")
        run_ip_mroute_show()
        print("-" * 30)

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if sock:
            sock.close()

if __name__ == "__main__":
    main()