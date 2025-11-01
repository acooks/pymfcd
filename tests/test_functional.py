# tests/test_functional.py
import json  # Added import
import os
import signal
import subprocess
import sys
import time

import pytest

from pyroute2 import IPDB, NetNS

# Mark all tests in this file as requiring root privileges
pytestmark = pytest.mark.skipif(
    os.geteuid() != 0, reason="Functional tests require root privileges"
)


@pytest.fixture
def netns_env(tmp_path):
    """
    A pytest fixture that sets up a complete, isolated network environment
    for functional testing.

    - Creates a network namespace.
    - Creates two veth pairs for IIF and OIF.
    - Configures the interfaces inside the namespace.
    - Starts the daemon inside the namespace.
    - Yields the namespace name and socket path.
    - Cleans everything up on teardown.
    """
    ns_name = "functest-ns"
    socket_path = str(tmp_path / "mfc_daemon.sock")
    state_file = str(tmp_path / "mfc_state.json")

    ipdb = IPDB()

    # --- Setup ---
    try:
        # Create namespace
        NetNS(ns_name)

        # Create and configure interfaces
        ipdb.create(kind="veth", ifname="veth-in-h", peer="veth-in-p").commit()
        ipdb.create(kind="veth", ifname="veth-out-h", peer="veth-out-p").commit()

        with ipdb.interfaces["veth-in-p"] as v:
            v.net_ns_fd = ns_name
        with ipdb.interfaces["veth-out-p"] as v:
            v.net_ns_fd = ns_name

        with IPDB(nl=NetNS(ns_name)) as ipdb_ns:
            with ipdb_ns.interfaces["veth-in-p"] as v:
                v.add_ip("10.0.1.1/24")
                v.up()
                v.multicast = 1
            with ipdb_ns.interfaces["veth-out-p"] as v:
                v.add_ip("10.0.2.1/24")
                v.up()
                v.multicast = 1

        # Start the daemon in a separate process inside the namespace
        daemon_cmd = [
            "ip",
            "netns",
            "exec",
            ns_name,
            sys.executable,
            "-m",
            "src.daemon_main",  # Run as a module
            "--socket-path",
            socket_path,
            "--state-file",
            state_file,
        ]
        daemon_process = subprocess.Popen(daemon_cmd, preexec_fn=os.setsid)

        # Wait for the daemon to be ready
        time.sleep(1)
        assert daemon_process.poll() is None, "Daemon failed to start"

        yield ns_name, socket_path

    finally:
        # --- Teardown ---
        if "daemon_process" in locals() and daemon_process.poll() is None:
            # Use process group kill to ensure daemon and any children are terminated
            os.killpg(os.getpgid(daemon_process.pid), signal.SIGTERM)
            try:
                daemon_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(daemon_process.pid), signal.SIGKILL)
                daemon_process.wait()

        if os.path.exists(f"/var/run/netns/{ns_name}"):
            subprocess.run(
                ["ip", "netns", "del", ns_name], check=False, capture_output=True
            )

        ipdb.release()


def run_cli(socket_path, command):
    """Helper to run the CLI tool as a subprocess."""
    cli_cmd = [
        sys.executable,
        "-m",
        "src.mfc_cli",
        f"--socket-path={socket_path}",
    ] + command

    print(f"Running CLI: {' '.join(cli_cmd)}")
    result = subprocess.run(cli_cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        print(f"CLI Error:\n{result.stderr}")
    assert result.returncode == 0

    print(f"CLI Output:\n{result.stdout}")
    return json.loads(result.stdout)


def check_mroute_in_ns(ns_name, expected_substring):
    """Helper to check the output of 'ip mroute show' inside the namespace."""
    cmd = ["ip", "netns", "exec", ns_name, "ip", "mroute", "show"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"ip mroute show output:\n{result.stdout}")
    return expected_substring in result.stdout


def test_e2e_add_show_del_show(netns_env):
    """
    A full end-to-end test of the application.
    1. Add a multicast route using the CLI.
    2. Verify the route exists in the kernel using 'ip mroute show'.
    3. Delete the route using the CLI.
    4. Verify the route is gone from the kernel.
    """
    ns_name, socket_path = netns_env

    source = "10.0.1.10"
    group = "239.10.20.30"
    iif = "veth-in-p"
    oifs = "veth-out-p"

    # --- 1. Add the route ---
    print("\n--- Testing ADD ---")
    add_cmd = [
        "mfc",
        "add",
        "--source",
        source,
        "--group",
        group,
        "--iif",
        iif,
        "--oifs",
        oifs,
    ]
    run_cli(socket_path, add_cmd)

    # --- 2. Verify the route exists ---
    print("\n--- Verifying ADD ---")
    time.sleep(0.5)  # Give daemon a moment to process
    expected_route_str = f"({source},{group})"  # Note: no space after comma
    assert check_mroute_in_ns(ns_name, expected_route_str), (
        f"Route '{expected_route_str}' not found in kernel after add"
    )

    # --- 3. Delete the route ---
    print("\n--- Testing DEL ---")
    del_cmd = ["mfc", "del", "--source", source, "--group", group]
    run_cli(socket_path, del_cmd)

    # --- 4. Verify the route is gone ---
    print("\n--- Verifying DEL ---")
    time.sleep(0.5)
    assert not check_mroute_in_ns(ns_name, expected_route_str), (
        f"Route '{expected_route_str}' still found in kernel after del"
    )
