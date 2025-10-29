#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <linux/mroute.h>
#include <net/if.h> // For if_nametoindex, if_indextoname
#include <sys/ioctl.h> // For SIOCSIFADDR, SIOCSIFNETMASK, SIOCSIFFLAGS

// Helper to run shell commands
int run_shell_cmd(const char *cmd) {
    printf("[C Tool] Executing shell: %s\n", cmd);
    return system(cmd);
}

void die(const char *s) {
    perror(s);
    exit(1);
}

int main() {
    printf("[C Tool] Starting SINGLE VIF (veth) test...\n");

    // --- Setup a veth pair ---
    printf("[C Tool] Creating veth pair 'veth0'/'veth1'...\n");
    if (run_shell_cmd("ip link add veth0 type veth peer name veth1") != 0) die("ip link add");
    if (run_shell_cmd("ip link set veth0 up") != 0) die("ip link set veth0 up");
    if (run_shell_cmd("ip link set veth1 up") != 0) die("ip link set veth1 up");

    // Assign IP address to veth0
    printf("[C Tool] Assigning IP 192.168.1.1/24 to veth0...\n");
    if (run_shell_cmd("ip addr add 192.168.1.1/24 dev veth0") != 0) die("ip addr add veth0");

    // Enable multicast on veth0
    printf("[C Tool] Enabling multicast on veth0...\n");
    if (run_shell_cmd("ip link set veth0 multicast on") != 0) die("ip link set veth0 multicast on");

    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_IGMP);
    if (sock < 0) {
        die("socket");
    }

    printf("[C Tool] Sending MRT_INIT to kernel...\n");
    if (setsockopt(sock, IPPROTO_IP, MRT_INIT, &(int){1}, sizeof(int)) < 0) {
        die("setsockopt MRT_INIT");
    }

    // Get the ifindex of veth0
    unsigned int ifindex_veth0 = if_nametoindex("veth0");
    if (ifindex_veth0 == 0) {
        die("if_nametoindex for 'veth0'");
    }
    printf("[C Tool] Found ifindex for 'veth0': %u\n", ifindex_veth0);

    struct vifctl vc;
    memset(&vc, 0, sizeof(vc));
    vc.vifc_vifi = 0;
    vc.vifc_flags = VIFF_USE_IFINDEX;
    vc.vifc_lcl_ifindex = ifindex_veth0;

    printf("[C Tool] Adding VIF 0 using ifindex %u (veth0)...\n", ifindex_veth0);
    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_VIF, &vc, sizeof(vc)) < 0) {
        die("setsockopt MRT_ADD_VIF");
    }

    printf("\n[C Tool] >>> SUCCESS <<<
");
    printf("[C Tool] VIF 0 added successfully. Check with 'cat /proc/net/ip_mr_vif'.\n");
    printf("[C Tool] Running for 10 seconds...\n");

    sleep(10);

    printf("[C Tool] Shutting down. Sending MRT_DONE to kernel...\n");
    setsockopt(sock, IPPROTO_IP, MRT_DONE, &(int){1}, sizeof(int));
    close(sock);

    // --- Cleanup veth pair ---
    printf("[C Tool] Cleaning up veth pair...\n");
    if (run_shell_cmd("ip link del veth0") != 0) {
        perror("ip link del veth0 (cleanup)");
    }

    return 0;
}
