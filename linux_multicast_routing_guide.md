# A Practical Guide to Linux Multicast Routing

## 1. The Core Architecture: Control Plane and Data Plane

Linux multicast routing is built on a fundamental separation of concerns between the kernel (the **data plane**) and a userspace application (the **control plane**). Understanding this division is the key to mastering multicast on Linux.

*   **The Kernel (Data Plane):** The kernel acts as a high-performance but passive forwarding engine. It contains the low-level machinery to duplicate and route multicast packets at line rate but has no built-in intelligence to decide where those packets should go. It simply follows the rules it is given and drops everything else.

*   **Userspace (Control Plane):** A userspace daemon is the "brain" of the operation. It contains the policy and logic, deciding which multicast streams should be routed from where to where. It is solely responsible for programming the kernel's forwarding engine with the correct set of rules.

A critical consequence of this design is that a persistent userspace daemon is **absolutely required** for multicast routing to function. The kernel's multicast routing state is tied to the lifecycle of the process that initializes it. If a program simply adds a route and then exits, the kernel will automatically clean up and remove that route.

---

## 2. The Kernel's Data Plane: The Forwarding Engine

The kernel's forwarding engine has three primary components: the Multicast Forwarding Cache (MFC), Virtual Interfaces (VIFs), and the Reverse Path Forwarding (RPF) check.

### 2.1. The Multicast Forwarding Cache (MFC)

The MFC is the kernel's main lookup table for routing multicast packets. For every incoming multicast packet, the kernel consults the MFC to find a matching rule. An MFC entry, or "mroute", is a simple but powerful rule:

> **If a packet from `(Source IP, Group IP)` arrives on `Input_VIF`, then forward copies of it to `Output_VIF_1`, `Output_VIF_2`, etc.**

*   An `(S,G)` route is a **source-specific** route, identified by both a source and group address.
*   A `(*,G)` route is an **any-source** route, where the source is a wildcard. The kernel represents this by setting the source address field in the MFC entry to `0.0.0.0` (`INADDR_ANY`).

### 2.2. Virtual Interfaces (VIFs)

The MFC does not operate on network devices like `eth0` directly. Instead, it uses an abstraction called a **Virtual Interface (VIF)**. A VIF is a logical routing endpoint created by the control plane daemon. Each VIF is given a unique integer index and is mapped to a real network device.

Creating a VIF has several prerequisites:
1.  **`IFF_MULTICAST` Flag:** The underlying physical device must have its multicast flag enabled. This is done with `iproute2`:
    ```sh
    sudo ip link set dev eth1 multicast on
    ```
2.  **Local Address:** The VIF must be anchored to a valid IP address belonging to the underlying physical device. It cannot be `0.0.0.0`.

### 2.3. The Reverse Path Forwarding (RPF) Check

The RPF check is the kernel's primary loop-prevention and security mechanism. For every incoming multicast packet, the kernel asks:

> "Did this packet from `Source IP` arrive on the same interface I would use to send a unicast packet *back to* that `Source IP`?"

To answer this, the kernel performs a lookup in the standard unicast routing table for the packet's source address. If the interface for that unicast route does not match the interface the multicast packet arrived on, the packet is dropped.

#### Impact of `rp_filter`

This behavior is directly controlled by the `rp_filter` sysctl setting (e.g., `/proc/sys/net/ipv4/conf/all/rp_filter`). Understanding its modes is critical for troubleshooting:
*   **`0` (Disabled):** No RPF check is performed.
*   **`1` (Strict):** This is the default in modern kernels. The RPF check is performed as described above. The packet is dropped if the unicast route back to the source does not use the same interface the packet arrived on. This can cause issues in complex or asymmetric routing topologies.
*   **`2` (Loose):** The kernel checks if *any* interface on the system has a unicast route back to the source. The packet is only dropped if the source is not reachable at all. This is less secure but more forgiving in asymmetric routing scenarios.

### 2.4. Inspecting the Data Plane from Userspace

You can directly observe the state of the kernel's multicast engine using `iproute2` and the `procfs`.

*   **Using `iproute2`:** The `ip mroute show` command is the authoritative tool for viewing the MFC.
    ```sh
    $ ip mroute show
    (192.168.1.10, 239.1.2.3)      Iif: eth0      Oifs: eth1 eth2
    (*, 239.4.5.6)                Iif: eth1      Oifs: eth2
    ```
    This output shows two MFC entries. The first is a source-specific route, and the second is an any-source route.

*   **Using `procfs`:** The kernel exposes two key files for low-level inspection:
    *   `/proc/net/ip_mr_vif`: This file lists the VIFs that have been created.
        ```sh
        $ cat /proc/net/ip_mr_vif
        Interface  BytesIn   PktsIn  BytesOut  PktsOut Flags Local    Remote
        0   eth0  0         0       0         0       0000  AC1001FD 00000000
        1   eth1  0         0       0         0       0000  AC1002FD 00000000
        ```
        The `Interface` column shows the VIF index and the device it's mapped to. `Local` is the local IP address of the VIF.

    *   `/proc/net/ip_mr_cache`: This file shows the raw MFC entries.
        ```sh
        $ cat /proc/net/ip_mr_cache
        Group    Origin   Iif Pkts     Bytes    Wrong Oifs
        EF010203 C0A8010A 0   0        0        0     1:1 2:1
        ```
        This shows one entry for group `239.1.2.3` (`EF010203`) from source `192.168.1.10` (`C0A8010A`), arriving on VIF `0`. The `Oifs` column shows it will be forwarded to VIF `1` with a TTL threshold of `1` and VIF `2` with a TTL threshold of `1`.

---

## 3. The Control Plane API: Programming the Kernel

### 3.1. The Two-API Reality

A userspace daemon communicates with the kernel's multicast subsystem via two different APIs. They have distinct and non-overlapping roles:
*   **Use the legacy `setsockopt` API to write to the MFC.**
*   **Use the modern `rtnetlink` API to read from the MFC.**

### 3.2. The Write Path: The Legacy `setsockopt` API

The proven and correct way to **add, change, or delete** multicast routes is the legacy `setsockopt` API. This is the interface used by production daemons like `smcroute` and `pimd`.

The process involves five key commands on a raw IGMP socket:
1.  `MRT_INIT`: Activates the engine and registers the socket as the "master" controller.
2.  `MRT_ADD_VIF`: Creates a VIF.
3.  `MRT_ADD_MFC`: Adds a forwarding entry to the MFC.
4.  `MRT_DEL_MFC`: Deletes a forwarding entry.
5.  `MRT_DONE`: Deactivates the engine and cleans up all state.

#### Practical Example: C `setsockopt`

This C program demonstrates the correct use of the legacy `setsockopt` API to add two Virtual Interfaces (VIFs) and a Multicast Forwarding Cache (MFC) entry. This code has been rigorously tested and proven to work, providing a reliable baseline for understanding the kernel's expectations.

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h> // For inet_addr
#include <linux/mroute.h>

void die(const char *s) {
    perror(s);
    exit(1);
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <ifindex_in> <ifindex_out>\n", argv[0]);
        exit(1);
    }

    int ifindex_in = atoi(argv[1]);
    int ifindex_out = atoi(argv[2]);
    printf("[C Tool] Adding route: VIF 0 (ifindex %d) -> VIF 1 (ifindex %d)\n", ifindex_in, ifindex_out);

    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_IGMP);
    if (sock < 0) die("socket");

    if (setsockopt(sock, IPPROTO_IP, MRT_INIT, &(int){1}, sizeof(int)) < 0) die("setsockopt MRT_INIT");

    struct vifctl vc;

    // Add VIF 0 (input)
    memset(&vc, 0, sizeof(vc));
    vc.vifc_vifi = 0;
    vc.vifc_flags = VIFF_USE_IFINDEX;
    vc.vifc_lcl_ifindex = ifindex_in;
    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_VIF, &vc, sizeof(vc)) < 0) die("setsockopt MRT_ADD_VIF 0");

    // Add VIF 1 (output)
    memset(&vc, 0, sizeof(vc));
    vc.vifc_vifi = 1;
    vc.vifc_flags = VIFF_USE_IFINDEX;
    vc.vifc_lcl_ifindex = ifindex_out;
    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_VIF, &vc, sizeof(vc)) < 0) die("setsockopt MRT_ADD_VIF 1");

    // Add the MFC entry
    struct mfcctl mfc;
    memset(&mfc, 0, sizeof(mfc));
    mfc.mfcc_origin.s_addr = inet_addr("0.0.0.0");
    mfc.mfcc_mcastgrp.s_addr = inet_addr("239.1.2.3");
    mfc.mfcc_parent = 0; // Input is VIF 0
    mfc.mfcc_ttls[1] = 1; // Output is VIF 1

    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_MFC, &mfc, sizeof(mfc)) < 0) die("setsockopt MRT_ADD_MFC");

    printf("[C Tool] SUCCESS: VIFs and MFC entry added. Holding for 10s...\n");
    sleep(10);

    printf("[C Tool] Shutting down.\n");
    setsockopt(sock, IPPROTO_IP, MRT_DONE, &(int){1}, sizeof(int));
    close(sock);

    return 0;
}
```

### 3.3. The Read Path: The `rtnetlink` API

The modern `rtnetlink` API is the standard way to **read or dump** the contents of the MFC. This is what `ip mroute show` uses. It sends an `RTM_GETROUTE` message and filters the kernel's response for routes of type `RTN_MULTICAST`.

However, attempting to add a multicast route using `rtnetlink` (`RTM_NEWROUTE` with `rtm_type = RTN_MULTICAST`) will appear to succeed, but **it will not create a functional MFC entry.** Kernel source analysis reveals that `RTM_NEWROUTE` messages are handled by the generic **FIB (Forwarding Information Base) subsystem**, which manages unicast routes. It never communicates with the separate **IPMR (IP Multicast Routing) subsystem** that the `setsockopt` API controls.

### 3.4. Kernel-to-Userspace Communication: Upcalls

The legacy API also provides a channel for the kernel to send notifications *to* the daemon. If a multicast packet arrives for which there is no MFC entry (a "cache miss"), the kernel's `ip_mr_input` function calls `ipmr_cache_report`. This constructs a special raw IGMP message of type `IGMPMSG_NOCACHE` and queues it on the daemon's raw IGMP socket. The daemon receives this message, learns about the new stream, and can then decide whether to install a new MFC entry.

---

## 4. A Critical Limitation: The `MAXVIFS` Scalability Problem

While the legacy API is functional, it contains a major architectural flaw that severely limits its use in modern, large-scale networks: a hard-coded limit on the number of Virtual Interfaces (VIFs) it can manage.

The kernel's native multicast forwarding engine can only handle a maximum of **32 VIFs**.

This number, defined by a constant called `MAXVIFS`, is a historical artifact from the original BSD multicast implementation. Because this limit is baked into the fixed-size data structures used to communicate between the kernel and userspace daemons, it cannot be easily changed without breaking all existing multicast software.

This means that any control plane daemon—no matter how sophisticated—that relies on the kernel's native multicast engine is fundamentally limited to a forwarding plane of only 32 interfaces.

### Impact on Common Router Designs

In practice, the `MAXVIFS` limit makes the kernel's native multicast engine unsuitable for any scenario requiring a high density of interfaces, which is common in modern networking.

*   **Use Case 1: The Inter-VLAN Router:** A Linux server is often used as a router for multiple VLANs, with each VLAN configured as a logical sub-interface (e.g., `eth0.100`, `eth0.200`). To route multicast between these VLANs, a VIF must be created for each one. A network with more than 32 VLANs that need multicast service simply cannot be supported by this data plane.

*   **Use Case 2: The VPN Hub Router:** A Linux server acting as a central hub for branch office VPNs faces an even stricter limit. If each branch connects via a point-to-point tunnel (like GRE or IPsec), the hub needs one tunnel interface per branch. To distribute a multicast stream (e.g., for video conferencing or stock tickers) to all branches, it must create one VIF per tunnel. This means a hub router using the native kernel multicast engine can serve a maximum of 31 branches (reserving one VIF for the upstream link).

These examples show that for modern, highly-segmented, or software-defined networks, the `MAXVIFS` limit is not just a theoretical constraint but a practical barrier.

### Solution 1: Using an Alternative Data Plane - Open vSwitch

Modern SDN architectures solve the `MAXVIFS` problem by completely bypassing the kernel's legacy multicast engine. Instead of relying on the IPMR subsystem, they use a more flexible and scalable software data plane, most commonly Open vSwitch (OVS).

In this model, the roles are redefined:
*   **Control Plane:** A central SDN Controller (like Ryu or ONOS) takes over the role of the multicast routing daemon.
*   **Data Plane:** The OVS instances running on Linux hosts execute the forwarding and replication logic.

The controller uses the **OpenFlow protocol** to program OVS. For multicast, it uses a feature called **Group Tables**:
1.  The controller learns which hosts (connected to OVS ports) want to receive a multicast stream.
2.  It creates a "group table" entry in OVS that contains a list of all the output ports for that stream.
3.  It installs a flow rule that matches incoming packets for the multicast group and directs them to this group table entry.
4.  OVS then handles the packet replication and forwarding in its own data path, sending a copy to each port listed in the group.

Because this entire process happens within OVS and is managed by OpenFlow, it **never uses the kernel's VIFs or MFC table**. The scaling is limited by OVS's own capacity, which is far greater than the 32-VIF limit.

### Solution 2: Transforming Multicast into Unicast - EVPN and Ingress Replication

Another common solution, prevalent in modern data centers, is to use a sophisticated control plane like EVPN (Ethernet VPN) to manage multicast traffic across an overlay network like VXLAN. This approach solves the scaling problem by transforming a multicast replication task into a series of simple unicast sends.

The key components are:
*   **Control Plane:** A routing suite like **FRR (Free Range Routing)** runs on each server/router. It uses BGP with the EVPN address family to advertise which multicast groups are needed by local virtual machines or clients.
*   **Data Plane:** The kernel's standard **unicast IP forwarding path** is used to transport VXLAN-encapsulated packets.

The mechanism is called **Ingress Replication**:
1.  Using BGP EVPN, every router learns which of its peers need to receive a particular multicast stream.
2.  When a multicast packet arrives at the first router (the "ingress" point to the VXLAN fabric), this router looks up the list of all peers that need the packet.
3.  Instead of using multicast routing, it creates multiple copies of the packet. It then wraps each copy in a separate, unicast VXLAN header. The destination IP of each packet is the IP of one of the peers.
4.  The router then sends these standard unicast packets into the network.

This method completely avoids the kernel's IPMR subsystem. It leverages the highly optimized unicast forwarding path to achieve what is functionally multicast distribution. The scalability is limited by the performance of the BGP control plane and the server's ability to perform unicast packet replication, both of which are far more scalable than the `MAXVIFS` limit.

#### The Critical Distinction: Control Plane vs. Data Plane

It is essential to understand that simply using a modern control plane like FRR does not automatically solve the problem. If FRR is configured to act as a traditional PIM router, it will attempt to program the underlying kernel's IPMR data plane via the legacy `setsockopt` API. In this mode, FRR would still be bound by the `MAXVIFS=32` limit. The scalability of modern solutions comes from pairing a modern control plane (like EVPN) with a modern data plane (like VXLAN Ingress Replication or a userspace forwarder like VPP) that bypasses the kernel's legacy multicast engine entirely.

---

## 5. Advanced Concepts and Topics

### 5.1. Special VIF Types

The `vifc_flags` field allows for the creation of special-purpose VIFs:
*   **`VIFF_TUNNEL`:** Creates a DVMRP-style IP-in-IP tunnel. When a packet is forwarded to this VIF, the kernel encapsulates it in a new unicast IP header, allowing multicast traffic to traverse unicast-only network segments.
*   **`VIFF_REGISTER`:** Creates a special virtual interface for the PIM protocol. Packets forwarded to this VIF are not sent on the network; instead, they are intercepted by the kernel and passed up to the userspace PIM daemon for protocol-specific processing (i.e., sending a PIM Register message to the Rendezvous Point).

### 5.2. IPv6 Multicast Routing

IPv6 has a parallel set of commands and structures defined in `<linux/mroute6.h>`:
*   **Commands:** `MRT6_INIT`, `MRT6_ADD_MIF`, `MRT6_ADD_MFC`, etc.
*   **Structures:** `struct mif6ctl` (for VIFs) and `struct mf6cctl` (for MFC entries).
The logic is analogous to the IPv4 implementation.

### 5.3. Security and Permissions

Control over the MFC is a privileged operation. The kernel enforces this with a two-tiered security model:
1.  The initial `MRT_INIT` call requires the `CAP_NET_ADMIN` capability.
2.  Once a socket is registered via `MRT_INIT`, that specific socket is permitted to make further changes without the capability. Any other process attempting to modify the MFC must have `CAP_NET_ADMIN`.

### 5.4. Hardware Offload

Modern switch hardware can often handle multicast replication faster than the CPU. The kernel's `switchdev` framework supports this via a "hairpin" model. When an offloaded switch receives a multicast packet, it forwards it out the correct ports itself and sends a copy to the CPU with a special flag (`skb->offload_l3_fwd_mark`). When the kernel's forwarding logic sees this flag, it knows the hardware has already handled the packet and it skips creating redundant software-forwarded copies.

---

## 6. Conclusion

Linux multicast routing is a powerful system defined by a clear division of labor. The kernel provides a fast but simple data plane, while a required userspace daemon provides the intelligent control plane. Programming this system requires understanding its two distinct APIs: the modern `rtnetlink` API for reading state, and the legacy `setsockopt` API for writing state. By using these tools correctly, a developer can build both simple static multicast routers and complex, dynamic routing daemons.
