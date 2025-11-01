# tests/test_cli_output.py
import pytest
from unittest.mock import patch
import io
import json

from src.mfc_cli import _print_show_output, main


def test_print_show_output_format():
    """
    Tests the table formatting of the _print_show_output function.
    """
    response = {
        "status": "success",
        "payload": {
            "vif_map": {
                "eth0": {"vifi": 0, "ifindex": 2, "ref_count": 1},
                "eth1": {"vifi": 1, "ifindex": 3, "ref_count": 2},
            },
            "mfc_rules": [
                {
                    "source": "10.0.0.1",
                    "group": "239.0.0.1",
                    "iif": "eth0",
                    "oifs": ["eth1"],
                },
                {
                    "source": "10.0.0.2",
                    "group": "239.0.0.2",
                    "iif": "eth1",
                    "oifs": ["eth0", "eth1"],
                },
            ],
        },
    }

    expected_output = (
        "Virtual Interface Table (VIFs)\n"
        "VIF   Interface       Index      Ref Count \n"
        "---------------------------------------------\n"
        "0     eth0            2          1         \n"
        "1     eth1            3          2         \n"
        "\n"
        "Multicast Forwarding Cache (MFC)\n"
        "Source             Group              IIF             OIFs\n"
        "----------------------------------------------------------------------\n"
        "10.0.0.1           239.0.0.1          eth0            eth1\n"
        "10.0.0.2           239.0.0.2          eth1            eth0, eth1"
    )

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        _print_show_output(response)
        assert mock_stdout.getvalue().strip() == expected_output.strip()

def test_show_command_empty_state():
    """
    Tests the 'show' command with an empty state from the daemon.
    """
    response = {
        "status": "success",
        "payload": {
            "vif_map": {},
            "mfc_rules": [],
        },
    }

    expected_output = (
        "Virtual Interface Table (VIFs)\n"
        "  No VIFs configured.\n"
        "\n"
        "Multicast Forwarding Cache (MFC)\n"
        "  No MFC rules installed."
    )

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        _print_show_output(response)
        assert mock_stdout.getvalue().strip() == expected_output.strip()

@patch("src.mfc_cli.send_ipc_command")
def test_main_show_command_integration(mock_send_ipc):
    """
    Integration test for the main function handling the 'show' command.
    """
    response = {
        "status": "success",
        "payload": {
            "vif_map": {"eth0": {"vifi": 0, "ifindex": 2, "ref_count": 1}},
            "mfc_rules": [],
        },
    }
    mock_send_ipc.return_value = response

    expected_output = (
        "Virtual Interface Table (VIFs)\n"
        "VIF   Interface       Index      Ref Count \n"
        "---------------------------------------------\n"
        "0     eth0            2          1         \n"
        "\n"
        "Multicast Forwarding Cache (MFC)\n"
        "  No MFC rules installed."
    )

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        with patch("sys.argv", ["mfc_cli", "show"]):
            main()
            assert mock_stdout.getvalue().strip() == expected_output.strip()

@patch("src.mfc_cli.send_ipc_command")
def test_main_show_command_json_output(mock_send_ipc):
    """
    Tests that the 'show --json' command outputs raw JSON.
    """
    response = {
        "status": "success",
        "payload": {
            "vif_map": {"eth0": {"vifi": 0, "ifindex": 2, "ref_count": 1}},
            "mfc_rules": [],
        },
    }
    mock_send_ipc.return_value = response

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        with patch("sys.argv", ["mfc_cli", "show", "--json"]):
            main()
            # The output should be the JSON response
            # Use json.loads to normalize formatting
            assert json.loads(mock_stdout.getvalue()) == response

@patch("src.mfc_cli.send_ipc_command")
def test_main_other_command_json_output(mock_send_ipc):
    """
    Tests that non-'show' commands still output raw JSON.
    """
    response = {"status": "success", "message": "MFC entry added."}
    mock_send_ipc.return_value = response

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        with patch("sys.argv", ["mfc_cli", "mfc", "add", "--group", "224.1.1.1", "--iif", "eth0", "--oifs", "eth1"]):
             main()
             # The output should be the JSON response
             # Use json.loads to normalize formatting
             assert json.loads(mock_stdout.getvalue()) == response
