#include <stdio.h>
#include <stddef.h> // For offsetof
#include <linux/mroute.h> // For struct mfcctl

int main() {
    printf("sizeof(struct mfcctl): %zu\n", sizeof(struct mfcctl));
    printf("offsetof(mfcc_pkt_cnt): %zu\n", offsetof(struct mfcctl, mfcc_pkt_cnt));
    return 0;
}

