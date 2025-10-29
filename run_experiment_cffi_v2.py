
import subprocess
import time
import sys
import os
import traceback
from pyroute2 import IPDB, NetNS
from pyroute2.netlink.exceptions import NetlinkError

def run_command(cmd, check=True, capture_output=True):
    """Helper to run a shell command and print its output."""
    print(f"[Orchestrator] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=capture_output, text=True, check=check
        )
        if result and result.stdout:
            print(f"[Orchestrator] stdout: {result.stdout.strip()}")
        if result and result.stderr:
            print(f"[Orchestrator] stderr: {result.stderr.strip()}", file=sys.stderr)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        if e.stdout:
            print(f"Stdout:\n{e.stdout}", file=sys.stderr)
        if e.stderr:
            print(f"Stderr:\n{e.stderr}", file=sys.stderr)
        raise

def main():
    ipdb = IPDB()
    daemon_process = None
    ns_name = "ns-router-cffi"
    veth_in_host = "veth-in-cffi"
    veth_in_peer = "veth-in-peer"
    veth_out_host = "veth-out-cffi"
    veth_out_peer = "veth-out-peer"

    # Use a wrapper for cleanup to ensure it runs
    try:
        _main_logic(
            ipdb, daemon_process, ns_name,
            veth_in_host, veth_in_peer, veth_out_host, veth_out_peer
        )
    except Exception:
        # The _main_logic function will print its own detailed traceback
        print("[Orchestrator] Experiment failed. See error above.", file=sys.stderr)
        sys.exit(1)
    finally:
        # 5. Cleanup
        print("\n--- [Cleanup] ---")
        if daemon_process and daemon_process.poll() is None:
            daemon_process.terminate()
            print("[Cleanup] Terminated CFFI daemon.")

        try:
            if os.path.exists(f"/var/run/netns/{ns_name}"):
                run_command(["sudo", "ip", "netns", "del", ns_name], check=False)
        except Exception as e:
            print(f"[Cleanup] Error removing namespace (might already be gone): {e}", file=sys.stderr)

        # ipdb automatically cleans up interfaces it created when released
        ipdb.release()
        print("[Cleanup] IPDB released, veth pairs should be removed.")
        print("[Cleanup] Cleanup complete.")


def _main_logic(
    ipdb, daemon_process, ns_name,
    veth_in_host, veth_in_peer, veth_out_host, veth_out_peer
):
    try:
        # 1. Check for dependencies
        try:
            import cffi
        except ImportError:
            print(
                "FATAL: The 'cffi' library is required. Please install it using 'pip install cffi'",
                file=sys.stderr,
            )
            sys.exit(1)

        # 2. Setup namespaces and veth pairs
        print(f"--- [Setup] Setting up network namespace '{ns_name}' ---")
        NetNS(ns_name)

        print(f"[Setup] Creating veth pair {veth_in_host} <--> {veth_in_peer}")
        ipdb.create(kind="veth", ifname=veth_in_host, peer=veth_in_peer).commit()
        print(f"[Setup] Creating veth pair {veth_out_host} <--> {veth_out_peer}")
        ipdb.create(kind="veth", ifname=veth_out_host, peer=veth_out_peer).commit()

        # --- This is the corrected logic ---
        print(f"[Setup] Moving PEER interface '{veth_in_peer}' to namespace '{ns_name}'")
        with ipdb.interfaces[veth_in_peer] as v:
            v.net_ns_fd = ns_name
        print(f"[Setup] Moving PEER interface '{veth_out_peer}' to namespace '{ns_name}'")
        with ipdb.interfaces[veth_out_peer] as v:
            v.net_ns_fd = ns_name
        # ------------------------------------

        # Configure interfaces inside the namespace
        print(f"[Setup] Configuring interfaces inside '{ns_name}'...")
        with IPDB(nl=NetNS(ns_name)) as ipdb_r:
            with ipdb_r.interfaces[veth_in_peer] as v:
                v.add_ip("10.0.1.1/24")
                v.up()
                v.multicast = 1
                ifindex_in = v.index
                print(f"[Setup]  - '{veth_in_peer}' (idx {ifindex_in}) is UP with IP 10.0.1.1/24 and MULTICAST")
            with ipdb_r.interfaces[veth_out_peer] as v:
                v.add_ip("10.0.2.1/24")
                v.up()
                v.multicast = 1
                ifindex_out = v.index
                print(f"[Setup]  - '{veth_out_peer}' (idx {ifindex_out}) is UP with IP 10.0.2.1/24 and MULTICAST")

        time.sleep(1)

        # 3. Run the Python CFFI daemon
        print("\n--- [Execute] Running Python CFFI daemon ---")
        cmd = [
            "sudo", "ip", "netns", "exec", ns_name,
            sys.executable, "mfc_daemon_cffi.py", str(ifindex_in), str(ifindex_out),
        ]
        daemon_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        print("[Execute] Waiting for daemon to configure (2 seconds)...")
        time.sleep(2)

        # Check if the daemon exited prematurely
        if daemon_process.poll() is not None:
            stdout, stderr = daemon_process.communicate()
            print("\n[Execute] >>> DAEMON FAILED TO START <<<", file=sys.stderr)
            if stdout:
                print(f"Daemon stdout:\n{stdout}", file=sys.stderr)
            if stderr:
                print(f"Daemon stderr:\n{stderr}", file=sys.stderr)
            raise RuntimeError("CFFI daemon exited prematurely.")

        # 4. Verify the MFC state while the daemon is running
        print("\n--- [Verify] Verifying MFC state with 'ip mroute show' ---")
        mroute_output_result = run_command(
            ["sudo", "ip", "netns", "exec", ns_name, "ip", "mroute", "show"]
        )
        mroute_output = mroute_output_result.stdout if mroute_output_result else ""

        expected_route_part1 = "(0.0.0.0,239.1.2.3)"
        expected_route_part2 = f"Iif: {veth_in_peer}"
        expected_route_part3 = f"Oifs: {veth_out_peer}"

        if (
            expected_route_part1 in mroute_output
            and expected_route_part2 in mroute_output
            and expected_route_part3 in mroute_output
        ):
            print("\n[Verify] >>> VERIFICATION SUCCESS <<<")
            print("[Verify] The expected multicast route was found.")
        else:
            print("\n[Verify] >>> VERIFICATION FAILED <<<", file=sys.stderr)
            print("[Verify] The expected multicast route was NOT found.", file=sys.stderr)
            raise RuntimeError("MFC entry not found.")

        print("\n[Execute] Test successful. Terminating daemon...")

    except (KeyError, NetlinkError) as e:
        print(f"\n[Setup] FATAL ERROR: A network object was not found or failed to configure: {e}", file=sys.stderr)
        print("[Setup] This can happen if an interface name is incorrect or a namespace operation fails.", file=sys.stderr)
        traceback.print_exc()
        raise  # Re-raise to trigger cleanup
    except Exception as e:
        print(f"\n[Orchestrator] An unexpected error occurred in main logic:", file=sys.stderr)
        traceback.print_exc()
        raise  # Re-raise to trigger cleanup


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script needs to be run with sudo.", file=sys.stderr)
        sys.exit(1)
    main()
