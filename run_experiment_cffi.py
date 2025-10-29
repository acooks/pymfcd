import subprocess
import time
import sys
import os
from pyroute2 import IPDB, NetNS


def run_command(cmd, check=True, capture_output=True):
    """Helper to run a shell command and print its output."""
    print(f"[Orchestrator] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=capture_output, text=True, check=check
        )
        if result and result.stdout:
            print(result.stdout.strip())
        if result and result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
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

    try:
        # 1. Check for dependencies
        try:
            import cffi
        except ImportError:
            print(
                "ERROR: The 'cffi' library is required. Please install it using 'pip install cffi'",
                file=sys.stderr,
            )
            sys.exit(1)

        # 2. Setup namespaces and veth pairs
        print(f"--- Setting up network namespace '{ns_name}' ---")
        NetNS(ns_name)
        ipdb.create(kind="veth", ifname="veth-in-cffi", peer="veth-in-peer").commit()
        ipdb.create(kind="veth", ifname="veth-out-cffi", peer="veth-out-peer").commit()

        with ipdb.interfaces["veth-in-cffi"] as v:
            v.net_ns_fd = ns_name
        with ipdb.interfaces["veth-out-cffi"] as v:
            v.net_ns_fd = ns_name

        with IPDB(nl=NetNS(ns_name)) as ipdb_r:
            with ipdb_r.interfaces["veth-in-peer"] as v:
                v.add_ip("10.0.1.1/24")
                v.up()
                v.multicast = 1
                ifindex_in = v.index
            with ipdb_r.interfaces["veth-out-peer"] as v:
                v.add_ip("10.0.2.1/24")
                v.up()
                v.multicast = 1
                ifindex_out = v.index

        print(
            f"Interfaces created in {ns_name}: veth-in-peer={ifindex_in}, veth-out-peer={ifindex_out}"
        )
        time.sleep(1)

        # 3. Run the Python CFFI daemon
        print("\n--- Running Python CFFI daemon ---")
        cmd = [
            "sudo",
            "ip",
            "netns",
            "exec",
            ns_name,
            sys.executable,
            "mfc_daemon_cffi.py",
            str(ifindex_in),
            str(ifindex_out),
        ]
        daemon_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        print("[Orchestrator] Waiting for daemon to configure (2 seconds)...")
        time.sleep(2)

        # Check if the daemon exited prematurely
        if daemon_process.poll() is not None:
            stdout, stderr = daemon_process.communicate()
            print("\n[Orchestrator] >>> DAEMON FAILED TO START <<<", file=sys.stderr)
            if stdout:
                print(f"Daemon stdout:\n{stdout}", file=sys.stderr)
            if stderr:
                print(f"Daemon stderr:\n{stderr}", file=sys.stderr)
            raise RuntimeError("CFFI daemon exited prematurely.")

        # 4. Verify the MFC state while the daemon is running
        print("\n--- Verifying MFC state with 'ip mroute show' ---")
        mroute_output_result = run_command(
            ["sudo", "ip", "netns", "exec", ns_name, "ip", "mroute", "show"]
        )
        mroute_output = mroute_output_result.stdout if mroute_output_result else ""

        expected_route_part1 = "(0.0.0.0,239.1.2.3)"
        expected_route_part2 = "Iif: veth-in-peer"
        expected_route_part3 = "Oifs: veth-out-peer"

        if (
            expected_route_part1 in mroute_output
            and expected_route_part2 in mroute_output
            and expected_route_part3 in mroute_output
        ):
            print("\n[Orchestrator] >>> VERIFICATION SUCCESS <<<")
            print("The expected multicast route was found.")
        else:
            print("\n[Orchestrator] >>> VERIFICATION FAILED <<<", file=sys.stderr)
            print("The expected multicast route was NOT found.", file=sys.stderr)
            raise RuntimeError("MFC entry not found.")

        print("\n[Orchestrator] Test successful. Terminating daemon...")

    except Exception as e:
        print(f"\nAn error occurred during the experiment: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # 5. Cleanup
        print("\n--- Cleaning up ---")
        if daemon_process and daemon_process.poll() is None:
            daemon_process.terminate()
            print("Terminated CFFI daemon.")

        if os.path.exists(f"/var/run/netns/{ns_name}"):
            run_command(["sudo", "ip", "netns", "del", ns_name], check=False)
            print(f"Namespace '{ns_name}' removed.")

        ipdb.release()
        print("Cleanup complete.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script needs to be run with sudo.", file=sys.stderr)
        sys.exit(1)
    main()
