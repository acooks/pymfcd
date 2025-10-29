import subprocess
import time
import sys
import os
import traceback
from pyroute2 import IPDB, NetNS


def log(message, file=None):
    """Helper for logging with a clear prefix."""
    print(f"[Orchestrator] {message}", flush=True, file=file)


def run_ns_command(ns_name, command, check=True):
    """Helper to run a command inside a namespace."""
    full_cmd = ["sudo", "ip", "netns", "exec", ns_name] + command
    log(f"Running in {ns_name}: {' '.join(command)}")
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, check=check)
        # Print stdout/stderr only if they contain something
        if result.stdout.strip():
            log(f"  --> stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            log(f"  --> stderr: {result.stderr.strip()}", file=sys.stderr)
        return result.stdout
    except subprocess.CalledProcessError as e:
        log(f"Command failed: {e}", file=sys.stderr)
        if e.stdout:
            log(f"Stdout:\n{e.stdout}", file=sys.stderr)
        if e.stderr:
            log(f"Stderr:\n{e.stderr}", file=sys.stderr)
        raise


def main():
    # --- Configuration ---
    ns_name = "mfc-lab"
    veth_in_host, veth_in_peer = "veth-in-h", "veth-in-p"
    veth_out_host, veth_out_peer = "veth-out-h", "veth-out-p"
    daemon_script = "mfc_daemon_instructive.py"

    ipdb = IPDB()
    daemon_process = None

    try:
        # --- [Setup] Phase ---
        log("--- [Setup] Phase ---")
        NetNS(ns_name)
        log(f"Created namespace '{ns_name}'.")

        ipdb.create(kind="veth", ifname=veth_in_host, peer=veth_in_peer).commit()
        log(f"Created veth pair {veth_in_host} <--> {veth_in_peer}.")
        ipdb.create(kind="veth", ifname=veth_out_host, peer=veth_out_peer).commit()
        log(f"Created veth pair {veth_out_host} <--> {veth_out_peer}.")

        with ipdb.interfaces[veth_in_peer] as v:
            v.net_ns_fd = ns_name
        with ipdb.interfaces[veth_out_peer] as v:
            v.net_ns_fd = ns_name
        log(f"Moved peer interfaces into '{ns_name}'.")

        with IPDB(nl=NetNS(ns_name)) as ipdb_r:
            with ipdb_r.interfaces[veth_in_peer] as v:
                v.add_ip("10.0.1.1/24")
                v.up()
                v.multicast = 1
                ifindex_in = v.index
            with ipdb_r.interfaces[veth_out_peer] as v:
                v.add_ip("10.0.2.1/24")
                v.up()
                v.multicast = 1
                ifindex_out = v.index
        log(
            f"Configured interfaces inside namespace: '{veth_in_peer}' (idx {ifindex_in}) and '{veth_out_peer}' (idx {ifindex_out})."
        )

        # --- [Verification: Before] Phase ---
        log("\n--- [Verification: Before] Phase ---")
        log("Checking initial kernel state inside the namespace...")
        run_ns_command(ns_name, ["cat", "/proc/net/ip_mr_vif"])
        run_ns_command(ns_name, ["ip", "mroute", "show"])
        log("Initial state is clean, as expected.")

        # --- [Execution] Phase ---
        log("\n--- [Execution] Phase ---")
        cmd = [
            "sudo",
            "ip",
            "netns",
            "exec",
            ns_name,
            sys.executable,
            daemon_script,
            str(ifindex_in),
            str(ifindex_out),
        ]
        log(f"Starting daemon: {' '.join(cmd)}")
        daemon_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        log("Waiting 3 seconds for daemon to initialize...")
        time.sleep(3)

        if daemon_process.poll() is not None:
            stdout, stderr = daemon_process.communicate()
            log("DAEMON FAILED TO START.", file=sys.stderr)
            if stdout:
                log(f"Daemon stdout:\n{stdout}", file=sys.stderr)
            if stderr:
                log(f"Daemon stderr:\n{stderr}", file=sys.stderr)
            raise RuntimeError("Daemon exited prematurely.")
        log("Daemon started successfully.")

        # --- [Verification: After] Phase ---
        log("\n--- [Verification: After] Phase ---")
        log("Checking kernel state after daemon initialization...")
        run_ns_command(ns_name, ["cat", "/proc/net/ip_mr_vif"])
        mroute_output = run_ns_command(ns_name, ["ip", "mroute", "show"])

        if (
            "(0.0.0.0,239.1.2.3)" in mroute_output
            and f"Iif: {veth_in_peer}" in mroute_output
        ):
            log(
                ">>> VERIFICATION SUCCESS: The multicast route was found in the kernel. <<<"
            )
        else:
            log(
                ">>> VERIFICATION FAILED: The multicast route was NOT found. <<<",
                file=sys.stderr,
            )
            raise RuntimeError("MFC entry verification failed.")

    except Exception:
        log("\n--- [Error] An unexpected error occurred. ---", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    finally:
        # --- [Cleanup] Phase ---
        log("\n--- [Cleanup] Phase ---")
        if daemon_process and daemon_process.poll() is None:
            log("Terminating daemon...")
            daemon_process.terminate()
        if os.path.exists(f"/var/run/netns/{ns_name}"):
            run_ns_command(
                ns_name, ["echo", "Cleaning up..."], check=False
            )  # Dummy command to show we are in ns
            NetNS(ns_name).close()  # Release file descriptor
            subprocess.run(["sudo", "ip", "netns", "del", ns_name], check=False)
            log(f"Namespace '{ns_name}' removed.")
        ipdb.release()
        log("IPDB released, veth pairs removed.")
        log("Cleanup complete.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script needs to be run with sudo.", file=sys.stderr)
        sys.exit(1)
    main()
