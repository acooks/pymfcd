#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <linux/mroute.h>
#include <net/if.h> // For if_nametoindex

void die(const char *s) {
    perror(s);
    exit(1);
}

int main() {
    printf("[C Tool] Starting SINGLE VIF test...\n");

    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_IGMP);
    if (sock < 0) {
        die("socket");
    }

    printf("[C Tool] Sending MRT_INIT to kernel...\n");
    if (setsockopt(sock, IPPROTO_IP, MRT_INIT, &(int){1}, sizeof(int)) < 0) {
        die("setsockopt MRT_INIT");
    }

    // Get the ifindex of the loopback interface 'lo'
    unsigned int ifindex_lo = if_nametoindex("lo");
    if (ifindex_lo == 0) {
        die("if_nametoindex for 'lo'");
    }
    printf("[C Tool] Found ifindex for 'lo': %u\n", ifindex_lo);

    struct vifctl vc;
    memset(&vc, 0, sizeof(vc));
    vc.vifc_vifi = 0;
    vc.vifc_flags = VIFF_USE_IFINDEX;
    vc.vifc_lcl_ifindex = ifindex_lo;

    printf("[C Tool] Adding VIF 0 using ifindex %u...\n", ifindex_lo);
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

    return 0;
}
