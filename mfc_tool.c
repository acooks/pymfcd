#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <linux/mroute.h>

void die(const char *s) {
    perror(s);
    exit(1);
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <ifindex1> <ifindex2>\n", argv[0]);
        exit(1);
    }

    int ifindex0 = atoi(argv[1]);
    int ifindex1 = atoi(argv[2]);

    printf("[C Tool] Starting C multicast tool...\n");

    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_IGMP);
    if (sock < 0) {
        die("socket");
    }

    printf("[C Tool] Sending MRT_INIT to kernel...\n");
    if (setsockopt(sock, IPPROTO_IP, MRT_INIT, &(int){1}, sizeof(int)) < 0) {
        die("setsockopt MRT_INIT");
    }

    struct vifctl vc;

    // Add VIF 0
    memset(&vc, 0, sizeof(vc));
    vc.vifc_vifi = 0;
    vc.vifc_flags = VIFF_USE_IFINDEX;
    vc.vifc_lcl_ifindex = ifindex0;
    printf("[C Tool] Adding VIF 0 using ifindex %d...\n", ifindex0);
    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_VIF, &vc, sizeof(vc)) < 0) {
        die("setsockopt MRT_ADD_VIF for VIF 0");
    }

    // Add VIF 1
    memset(&vc, 0, sizeof(vc));
    vc.vifc_vifi = 1;
    vc.vifc_flags = VIFF_USE_IFINDEX;
    vc.vifc_lcl_ifindex = ifindex1;
    printf("[C Tool] Adding VIF 1 using ifindex %d...\n", ifindex1);
    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_VIF, &vc, sizeof(vc)) < 0) {
        die("setsockopt MRT_ADD_VIF for VIF 1");
    }

    struct mfcctl mfc;
    memset(&mfc, 0, sizeof(mfc));
    mfc.mfcc_origin.s_addr = inet_addr("0.0.0.0");
    mfc.mfcc_mcastgrp.s_addr = inet_addr("239.1.2.3");
    mfc.mfcc_parent = 0;
    mfc.mfcc_ttls[1] = 1; // Set TTL threshold for VIF 1

    printf("[C Tool] Adding MFC entry for (*, 239.1.2.3) from VIF 0 to VIF 1...\n");
    if (setsockopt(sock, IPPROTO_IP, MRT_ADD_MFC, &mfc, sizeof(mfc)) < 0) {
        // This is the call that fails in Python.
        die("setsockopt MRT_ADD_MFC");
    }

    printf("\n[C Tool] >>> SUCCESS <<<
");
    printf("[C Tool] Multicast route added successfully.\n");
    printf("[C Tool] Running for 10 seconds...\n");

    sleep(10);

    printf("[C Tool] Shutting down. Sending MRT_DONE to kernel...\n");
    setsockopt(sock, IPPROTO_IP, MRT_DONE, &(int){1}, sizeof(int));
    close(sock);

    return 0;
}
