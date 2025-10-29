package main

import (
	"fmt"
	"log"

	"github.com/vishvananda/netlink"
)

func main() {
	// MfcGet retrieves the multicast forwarding cache from the kernel.
	// This requires sufficient privileges to access netlink sockets.
	mfcStats, err := netlink.MfcGet()
	if err != nil {
		log.Fatalf("Failed to get MFC stats: %v. Try running with sudo.", err)
	}

	if len(mfcStats) == 0 {
		fmt.Println("Multicast Forwarding Cache is empty.")
		fmt.Println("This may be because multicast routing is not enabled or no multicast traffic is flowing.")
		return
	}

	fmt.Println("Kernel Multicast Forwarding Cache (MFC):")
	fmt.Println("-----------------------------------------")

	// Iterate over the MFC entries and print the details for each.
	for i, entry := range mfcStats {
		fmt.Printf("Entry %d:\n", i+1)
		fmt.Printf("  Source Address:      %s\n", entry.MfcOrigin)
		fmt.Printf("  Multicast Group:     %s\n", entry.MfcMcastgrp)
		fmt.Printf("  Parent Iface Index:  %d\n", entry.MfcParent)
		fmt.Printf("  Packets Forwarded:   %d\n", entry.Packets)
		fmt.Printf("  Bytes Forwarded:     %d\n", entry.Bytes)
		fmt.Printf("  Packets on Wrong If: %d\n", entry.WrongIf)
		fmt.Println("-----------------------------------------")
	}
}
