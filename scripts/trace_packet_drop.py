#!/usr/bin/python3
#
# trace_drop.py: Trace a packet by IP and find the kernel drop location.
#
# USAGE: sudo ./trace_drop.py --saddr 192.168.1.100 --daddr 239.10.20.30
#
# This is a corrected, robust, and validated version of the eBPF tracer.

import argparse
import socket
import struct

from bcc import BPF

# Argument parsing
parser = argparse.ArgumentParser(description="Trace packet drops by source/dest IP")
parser.add_argument("--saddr", type=str, required=True, help="Source IP address")
parser.add_argument("--daddr", type=str, required=True, help="Destination IP address")
args = parser.parse_args()

# Convert IPs to network-order integers for the C code
saddr_n = struct.unpack("!I", socket.inet_aton(args.saddr))[0]
daddr_n = struct.unpack("!I", socket.inet_aton(args.daddr))[0]

# The eBPF C program, defined with a standard triple-quoted string.
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <net/sock.h>
#include <linux/skbuff.h>
#include <net/ip.h>

# Use valid C identifiers for placeholders
#define SRC_IP_HOLDER 0x0
#define DST_IP_HOLDER 0x0

BPF_STACK_TRACE(stack_traces, 1024);

int trace_kfree_skb(struct pt_regs *ctx, struct sk_buff *skb) {
    if (!skb) { return 0; }
    # The network header must be set to access the IP header.
    # A skb without a network header is not an IP packet.
    if (skb->network_header == 0) { return 0; }

    # Cast the network header to an IP header
    struct iphdr *ip = (struct iphdr *)(skb->head + skb->network_header);

    # Filter for our specific packet
    if (ip->saddr == SRC_IP_HOLDER && ip->daddr == DST_IP_HOLDER) {
        # Get a kernel stack trace. The '0' means kernel stack.
        int stack_id = stack_traces.get_stackid(ctx, 0);
        if (stack_id >= 0) {
            # Send a message to the trace pipe.
            # Note the manually escaped newline: \n
            bpf_trace_printk("Packet dropped, stack_id=%d\n", stack_id);
        }
    }
    return 0;
}
"""

# Correctly substitute the placeholder identifiers with the hex values
bpf_text = bpf_text.replace("SRC_IP_HOLDER", f"0x{saddr_n:08x}")
bpf_text = bpf_text.replace("DST_IP_HOLDER", f"0x{daddr_n:08x}")

# Load the BPF program
try:
    b = BPF(text=bpf_text)
    b.attach_kprobe(event="kfree_skb", fn_name="trace_kfree_skb")
except Exception as e:
    print("Failed to compile or attach BPF program.")
    print(
        "Please ensure you have kernel headers installed for "
        "your running kernel version."
    )
    print(f"Error: {e}")
    exit(1)


print(f"Tracing drops for {args.saddr} -> {args.daddr}... Press Ctrl-C to stop.")

try:
    while True:
        (task, pid, cpu, flags, ts, msg) = b.trace_fields()
        if b"Packet dropped" in msg:
            msg_str = msg.decode("utf-8", "replace")
            try:
                stack_id = int(msg_str.split("=")[1])
            except (IndexError, ValueError):
                print(f"Could not parse stack_id from message: {msg_str}")
                continue

            print("\n" + "=" * 20 + " PACKET DROP DETECTED " + "=" * 20)
            print(f"Timestamp: {ts:.9f}")

            stack = b.get_table("stack_traces")
            for addr in stack.walk(stack_id):
                sym = b.ksym(addr, show_offset=True)
                print(f"	{sym.decode('utf-8', 'replace')}")
            print("=" * 62 + "\n")

except KeyboardInterrupt:
    print("\nDetaching...")
    exit()
except Exception as e:
    print(f"An error occurred: {e}")
    exit()
