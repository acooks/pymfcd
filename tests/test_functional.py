# tests/test_functional.py
import json  # Added import
import os
import signal
import socket
import subprocess
import sys
import time

import pytest
from pyroute2 import NDB, netns

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

    ndb = NDB()

    # --- Setup ---

    try:

        # Create namespace

        netns.create(ns_name)

        ndb.sources.add(netns=ns_name, target=ns_name)

        # Create and configure interfaces

        # Create and configure interfaces
        with ndb.interfaces.create(
            kind="veth", ifname="veth-in-h", peer="veth-in-p"
        ) as veth_in:
            veth_in.set(state="up").commit()

        with ndb.interfaces.create(
            kind="veth", ifname="veth-out-h", peer="veth-out-p"
        ) as veth_out:
            veth_out.set(state="up").commit()

        subprocess.run(
            ["ip", "link", "set", "veth-in-p", "netns", ns_name], check=True
        )
        subprocess.run(
            ["ip", "link", "set", "veth-out-p", "netns", ns_name], check=True
        )
        # Configure interfaces inside the namespace
        subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                ns_name,
                "ip",
                "link",
                "set",
                "veth-in-p",
                "up",
            ],
            check=True,
        )
        subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                ns_name,
                "ip",
                "addr",
                "add",
                "10.0.1.1/24",
                "dev",
                "veth-in-p",
            ],
            check=True,
        )
        subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                ns_name,
                "ip",
                "link",
                "set",
                "dev",
                "veth-in-p",
                "multicast",
                "on",
            ],
            check=True,
        )

        subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                ns_name,
                "ip",
                "link",
                "set",
                "veth-out-p",
                "up",
            ],
            check=True,
        )
        subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                ns_name,
                "ip",
                "addr",
                "add",
                "10.0.2.1/24",
                "dev",
                "veth-out-p",
            ],
            check=True,
        )
        subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                ns_name,
                "ip",
                "link",
                "set",
                "dev",
                "veth-out-p",
                "multicast",
                "on",
            ],
            check=True,
        )
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

        # Wait for the daemon to be ready by polling the socket

        start_time = time.monotonic()

        socket_ready = False

        while time.monotonic() - start_time < 5:  # 5-second timeout

            if daemon_process.poll() is not None:

                pytest.fail("Daemon process terminated unexpectedly during startup.")

            try:

                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:

                    s.connect(socket_path)

                socket_ready = True

                break

            except (FileNotFoundError, ConnectionRefusedError):

                time.sleep(0.1)  # Wait 100ms before retrying

        if not socket_ready:

            pytest.fail("Daemon socket did not become available within 5 seconds.")

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

        # Clean up host-side veth interfaces
        for ifname in ["veth-in-h", "veth-out-h"]:
            try:
                # Check if the interface exists before trying to delete it
                subprocess.run(
                    ["ip", "link", "show", ifname], check=True, capture_output=True
                )
                subprocess.run(["ip", "link", "del", ifname], check=True)
                print(f"Cleaned up host interface: {ifname}")
            except subprocess.CalledProcessError:
                print(f"Host interface {ifname} did not exist or could not be deleted.")
            except Exception as e:
                print(f"Warning: Could not remove interface {ifname}: {e}")

        if os.path.exists(f"/var/run/netns/{ns_name}"):
            netns.remove(ns_name)
        ndb.close()


def run_cli(socket_path, command):
    """Helper to run the CLI tool as a subprocess."""
    cli_cmd = [
        sys.executable,
        "-m",
        "src.mfc_cli",
        f"--socket-path={socket_path}",
    ] + command

    # Create a copy of the current environment and set PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    print(f"Running CLI: {' '.join(cli_cmd)}")
    result = subprocess.run(
        cli_cmd, capture_output=True, text=True, check=False, env=env
    )

    # --- Enhanced Debugging ---
    print(f"CLI raw stdout:\n---\n{result.stdout}\n---")
    print(f"CLI raw stderr:\n---\n{result.stderr}\n---")
    # --------------------------

    # if result.returncode != 0:
    #     print(f"CLI Error:\n{result.stderr}")
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
    assert check_mroute_in_ns(
        ns_name, expected_route_str
    ), f"Route '{expected_route_str}' not found in kernel after add"

    # --- 3. Delete the route ---
    print("\n--- Testing DEL ---")
    del_cmd = ["mfc", "del", "--source", source, "--group", group]
    run_cli(socket_path, del_cmd)

    # --- 4. Verify the route is gone ---
    print("\n--- Verifying DEL ---")
    time.sleep(0.5)
    assert not check_mroute_in_ns(
        ns_name, expected_route_str
    ), f"Route '{expected_route_str}' still found in kernel after del"
