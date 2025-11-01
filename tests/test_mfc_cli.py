# tests/test_mfc_cli.py
from unittest.mock import patch

from src.mfc_cli import main


@patch("src.mfc_cli.send_ipc_command")
def test_cli_add_mfc(mock_send_ipc):
    """Tests that the 'mfc add' command constructs the correct JSON payload."""
    mock_send_ipc.return_value = {"status": "success"}

    # Simulate command line arguments
    sys_argv = [
        "mfc_cli.py",
        "mfc",
        "add",
        "--source",
        "1.1.1.1",
        "--group",
        "239.1.1.1",
        "--iif",
        "eth0",
        "--oifs",
        "eth1,eth2",
    ]

    with patch("sys.argv", sys_argv):
        main()

    mock_send_ipc.assert_called_once_with(
        "/var/run/mfc_daemon.sock",
        {
            "action": "ADD_MFC",
            "payload": {
                "source": "1.1.1.1",
                "group": "239.1.1.1",
                "iif": "eth0",
                "oifs": ["eth1", "eth2"],
            },
        },
    )


@patch("src.mfc_cli.send_ipc_command")
def test_cli_del_mfc(mock_send_ipc):
    """Tests that the 'mfc del' command constructs the correct JSON payload."""
    mock_send_ipc.return_value = {"status": "success"}

    sys_argv = [
        "mfc_cli.py",
        "mfc",
        "del",
        "--group",
        "239.1.1.1",
    ]

    with patch("sys.argv", sys_argv):
        main()

    mock_send_ipc.assert_called_once_with(
        "/var/run/mfc_daemon.sock",
        {
            "action": "DEL_MFC",
            "payload": {
                "source": "0.0.0.0",  # Default source
                "group": "239.1.1.1",
            },
        },
    )


@patch("src.mfc_cli.send_ipc_command")
def test_cli_show(mock_send_ipc):
    """Tests that the 'show' command constructs the correct JSON payload."""
    # Simulate a response from the daemon
    mock_send_ipc.return_value = {
        "status": "success",
        "payload": {
            "vif_map": {
                "eth0": {"vifi": 0, "ifindex": 2, "ref_count": 1},
                "eth1": {"vifi": 1, "ifindex": 3, "ref_count": 1},
            },
            "mfc_rules": [
                {"source": "1.1.1.1", "group": "239.1.1.1", "iif": "eth0", "oifs": ["eth1"]},
            ],
        },
    }

    sys_argv = ["mfc_cli.py", "show"]

    with patch("sys.argv", sys_argv):
        main()

    mock_send_ipc.assert_called_once_with(
        "/var/run/mfc_daemon.sock", {"action": "SHOW"}
    )
