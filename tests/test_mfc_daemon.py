# tests/test_mfc_daemon.py
import pytest
from unittest.mock import patch, MagicMock
import socket

from src.mfc_daemon import MfcDaemon
from src.kernel_ffi import KernelInterface

@patch('src.mfc_daemon.KernelInterface')
def test_daemon_initialization(MockKernelInterface):
    """
    Tests that the MfcDaemon class correctly initializes its
    KernelInterface dependency.
    """
    mock_ki_instance = MockKernelInterface.return_value
    
    daemon = MfcDaemon()
    
    # Verify that KernelInterface was instantiated
    MockKernelInterface.assert_called_once()
    assert daemon.ki is mock_ki_instance
    
    # Verify that the daemon's internal state is initialized and empty
    assert daemon.vif_map == {}
    assert daemon.mfc_rules == []


@patch('src.mfc_daemon.KernelInterface')
def test_add_mfc_rule_new_vifs(MockKernelInterface):
    """
    Tests the core logic of add_mfc_rule, including the automatic
    creation of VIFs for new interfaces.
    """
    mock_ki = MockKernelInterface.return_value
    daemon = MfcDaemon()

    source = "192.168.1.10"
    group = "239.1.2.3"
    iif = "eth0"
    oifs = ["eth1", "eth2"]

    # Mock the get_ifindex function to return dummy indices
    with patch('src.mfc_daemon.get_ifindex') as mock_get_ifindex:
        mock_get_ifindex.side_effect = [10, 11, 12] # eth0, eth1, eth2

        daemon.add_mfc_rule(source, group, iif, oifs)

    # Verify VIFs were added for all new interfaces
    # Expect 3 calls: eth0, eth1, eth2
    assert mock_ki._add_vif.call_count == 3
    mock_ki._add_vif.assert_any_call(vifi=0, ifindex=10) # eth0 -> vifi 0
    mock_ki._add_vif.assert_any_call(vifi=1, ifindex=11) # eth1 -> vifi 1
    mock_ki._add_vif.assert_any_call(vifi=2, ifindex=12) # eth2 -> vifi 2

    # Verify MFC was added with the correct VIF indices
    mock_ki._add_mfc.assert_called_once_with(
        source_ip=source,
        group_ip=group,
        iif_vifi=0, # vifi for eth0
        oif_vifis=[1, 2] # vifis for eth1, eth2
    )

    # Verify internal state was updated
    assert daemon.vif_map == {"eth0": 0, "eth1": 1, "eth2": 2}
    expected_rule = {"source": source, "group": group, "iif": iif, "oifs": oifs}
    assert expected_rule in daemon.mfc_rules


@patch('src.mfc_daemon.KernelInterface')
def test_del_mfc_rule(MockKernelInterface):
    """
    Tests the core logic of del_mfc_rule.
    """
    mock_ki = MockKernelInterface.return_value
    daemon = MfcDaemon()

    # Pre-populate the state
    source = "192.168.1.10"
    group = "239.1.2.3"
    rule = {"source": source, "group": group, "iif": "eth0", "oifs": ["eth1"]}
    daemon.mfc_rules.append(rule)

    daemon.del_mfc_rule(source, group)

    # Verify the kernel interface was called to delete the rule
    mock_ki._del_mfc.assert_called_once_with(source_ip=source, group_ip=group)

    # Verify the rule was removed from the internal state
    assert rule not in daemon.mfc_rules


import threading
from src.common import send_ipc_command

@patch('src.mfc_daemon.KernelInterface')
def test_daemon_ipc_command_handling(MockKernelInterface, tmp_path):
    """
    Tests that the daemon's main run loop correctly listens on a UDS,
    receives a command, and dispatches it to the correct method.
    """
    socket_path = str(tmp_path / "test_daemon.sock")
    daemon = MfcDaemon()
    
    # Mock the internal method that will be called
    daemon.add_mfc_rule = MagicMock(return_value={"status": "success"})
    
    # Run the daemon's main loop in a background thread
    server_ready_event = threading.Event()
    server_thread = threading.Thread(target=daemon.run, args=(socket_path, server_ready_event))
    server_thread.daemon = True # Allows main thread to exit even if this one is running
    server_thread.start()

    server_ready_event.wait(timeout=1)
    assert server_ready_event.is_set(), "Daemon did not start listening in time"

    # Send a command from the client side
    command = {
        "action": "ADD_MFC",
        "payload": {
            "source": "1.1.1.1", "group": "239.1.1.1", "iif": "lo", "oifs": ["lo"]
        }
    }
    send_ipc_command(socket_path, command)

    # Stop the server loop
    daemon.stop()
    server_thread.join(timeout=2) # Allow time for the socket timeout to fire
    assert not server_thread.is_alive()

    # Verify that the command was received and dispatched correctly
    daemon.add_mfc_rule.assert_called_once_with(
        source="1.1.1.1", group="239.1.1.1", iif="lo", oifs=["lo"]
    )


import json
from unittest.mock import mock_open

@patch('src.mfc_daemon.KernelInterface')
def test_save_state_writes_correct_json(MockKernelInterface):
    """
    Tests that the save_state method correctly writes the daemon's
    internal state to a JSON file.
    """
    daemon = MfcDaemon()
    
    # Pre-populate the state
    daemon.vif_map = {"eth0": 0, "eth1": 1}
    daemon.mfc_rules = [{
        "source": "1.1.1.1", "group": "239.1.1.1", "iif": "eth0", "oifs": ["eth1"]
    }]
    
    state_file_path = "/fake/state.json"
    
    # Use mock_open to intercept the file write
    m = mock_open()
    with patch('builtins.open', m):
        daemon.save_state(state_file_path)

    # Verify the file was opened for writing
    m.assert_called_once_with(state_file_path, 'w')
    
    # Reconstruct the full string written to the file
    written_data = "".join(call.args[0] for call in m().write.call_args_list)
    
    expected_state = {
        "vif_map": {"eth0": 0, "eth1": 1},
        "mfc_rules": [{
            "source": "1.1.1.1", "group": "239.1.1.1", "iif": "eth0", "oifs": ["eth1"]
        }]
    }
    
    assert json.loads(written_data) == expected_state


@patch('src.mfc_daemon.KernelInterface')
def test_load_state_success(MockKernelInterface):
    """
    Tests that load_state correctly reads a state file, restores internal
    state, and re-applies the rules by calling add_mfc_rule.
    """
    daemon = MfcDaemon()
    # Mock the method that will be called by load_state
    daemon.add_mfc_rule = MagicMock()
    
    state_content = {
        "vif_map": {"eth0": 0, "eth1": 1},
        "mfc_rules": [{
            "source": "1.1.1.1", "group": "239.1.1.1", "iif": "eth0", "oifs": ["eth1"]
        }]
    }
    state_json = json.dumps(state_content)
    state_file_path = "/fake/state.json"

    m = mock_open(read_data=state_json)
    with patch('builtins.open', m):
        with patch('os.path.exists', return_value=True):
            daemon.load_state(state_file_path)

    # Verify internal state is restored BEFORE re-applying rules
    assert daemon.vif_map == {"eth0": 0, "eth1": 1}
    assert daemon._next_vifi == 2

    # Verify that add_mfc_rule was called to re-apply the state
    daemon.add_mfc_rule.assert_called_once_with(
        source="1.1.1.1", group="239.1.1.1", iif="eth0", oifs=["eth1"]
    )


@patch('src.mfc_daemon.KernelInterface')
def test_load_state_file_not_found(MockKernelInterface):
    """
    Tests that load_state handles a non-existent state file gracefully.
    """
    state_file_path = "/fake/state.json"
    
    with patch('os.path.exists', return_value=False):
        daemon = MfcDaemon()
        daemon.load_state(state_file_path)

    # Verify state remains empty
    assert daemon.vif_map == {}
    assert daemon.mfc_rules == []
    assert daemon._next_vifi == 0
    

@patch('src.mfc_daemon.KernelInterface')
def test_load_state_corrupted_json(MockKernelInterface):
    """
    Tests that load_state handles a corrupted state file gracefully.
    """
    state_file_path = "/fake/state.json"
    
    m = mock_open(read_data="{not valid json")
    with patch('builtins.open', m):
        with patch('os.path.exists', return_value=True):
            daemon = MfcDaemon()
            # We expect it to log an error, but not crash
            with patch('builtins.print') as mock_print:
                daemon.load_state(state_file_path)

    # Verify state remains empty
    assert daemon.vif_map == {}
    assert daemon.mfc_rules == []
    
    # Verify an error was logged
    mock_print.assert_any_call("[ERROR] Failed to load state from /fake/state.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)")


@patch('src.mfc_daemon.KernelInterface')
def test_add_mfc_transaction_rollback(MockKernelInterface):
    """
    Tests that if _add_mfc fails, any newly created VIFs are
    automatically deleted to roll back the transaction.
    """
    mock_ki = MockKernelInterface.return_value
    # Simulate the _add_mfc call failing
    mock_ki._add_mfc.side_effect = OSError(1, "Operation not permitted")
    
    daemon = MfcDaemon()

    # Mock get_ifindex
    with patch('src.mfc_daemon.get_ifindex') as mock_get_ifindex:
        mock_get_ifindex.side_effect = [10, 11] # iif, oif

        # We expect this call to fail, so we wrap it
        with pytest.raises(OSError):
            daemon.add_mfc_rule("1.1.1.1", "239.1.1.1", "eth0", ["eth1"])

    # Verify that _add_vif was called for the new interfaces
    assert mock_ki._add_vif.call_count == 2
    mock_ki._add_vif.assert_any_call(vifi=0, ifindex=10)
    mock_ki._add_vif.assert_any_call(vifi=1, ifindex=11)

    # CRITICAL: Verify that _del_vif was called to roll back the new VIFs
    assert mock_ki._del_vif.call_count == 2
    mock_ki._del_vif.assert_any_call(vifi=0, ifindex=10)
    mock_ki._del_vif.assert_any_call(vifi=1, ifindex=11)

    # Verify that the internal state is still clean
    assert daemon.vif_map == {}
    assert daemon.mfc_rules == []
    assert daemon._next_vifi == 0


import os
import signal
import time

@patch('src.mfc_daemon.KernelInterface')
def test_daemon_graceful_shutdown(MockKernelInterface, tmp_path):
    """
    Tests that the daemon's main_entrypoint correctly performs cleanup
    actions (save_state, mrt_done) when its run loop terminates.
    """
    socket_path = str(tmp_path / "test_shutdown.sock")
    state_path = str(tmp_path / "test_state.json")
    
    daemon = MfcDaemon()
    daemon.ki = MockKernelInterface.return_value
    daemon.save_state = MagicMock()
    
    # We will call stop() directly to simulate a signal
    def stop_daemon_after_a_moment():
        time.sleep(0.1)
        daemon.stop()

    stopper_thread = threading.Thread(target=stop_daemon_after_a_moment)
    stopper_thread.start()

    # This call will block until the run loop exits
    daemon.main_entrypoint(socket_path, state_path)

    stopper_thread.join()

    # Verify cleanup actions in the 'finally' block were performed
    daemon.save_state.assert_called_once_with(state_path)
    daemon.ki.mrt_done.assert_called_once()
