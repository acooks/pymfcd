# tests/test_cli_validation.py
import json
import sys
from unittest.mock import patch

import pytest

from src import mfc_cli


def run_cli_for_validation(monkeypatch, command, expected_exit_code=0):
    """
    Helper to run the CLI tool's main function for validation tests.
    """
    # Construct the full argv list
    argv = ["mfc_cli"] + command
    monkeypatch.setattr(sys, "argv", argv)

    try:
        mfc_cli.main()
    except SystemExit as e:
        assert e.code == expected_exit_code


@patch("src.mfc_cli.send_ipc_command")
def test_add_invalid_ip(mock_send_ipc_command, capsys):
    """Verify the daemon rejects an invalid group IP address."""
    socket_path = "/tmp/dummy.sock"
    mock_send_ipc_command.return_value = {
        "status": "error",
        "message": "Invalid IP address format",
    }
    cmd = [
        f"--socket-path={socket_path}",
        "mfc",
        "add",
        "--group",
        "not-an-ip",
        "--iif",
        "veth-in-p",
        "--oifs",
        "veth-out-p",
    ]

    # We don't expect a SystemExit here because the error is handled gracefully
    # by printing a JSON response to stdout.
    mfc_cli.main.__globals__["sys"].argv = ["mfc_cli"] + cmd
    mfc_cli.main()

    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert response["status"] == "error"
    assert "Invalid IP address format" in response["message"]


@patch("src.mfc_cli.send_ipc_command")
def test_del_nonexistent_rule(mock_send_ipc_command, capsys):
    """Verify the daemon returns an error when deleting a rule that does not exist."""
    socket_path = "/tmp/dummy.sock"
    mock_send_ipc_command.return_value = {"status": "error", "message": "not found"}
    cmd = [
        f"--socket-path={socket_path}",
        "mfc",
        "del",
        "--group",
        "239.255.255.250",
    ]

    mfc_cli.main.__globals__["sys"].argv = ["mfc_cli"] + cmd
    mfc_cli.main()

    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert response["status"] == "error"
    assert "not found" in response["message"]


def test_add_missing_group(monkeypatch):
    """Verify 'mfc add' fails without a --group."""
    socket_path = "/tmp/dummy.sock"
    cmd = [
        f"--socket-path={socket_path}",
        "mfc",
        "add",
        "--iif",
        "veth-in-p",
        "--oifs",
        "veth-out-p",
    ]
    # Argparse error should exit with code 2
    with pytest.raises(SystemExit) as e:
        mfc_cli.main.__globals__["sys"].argv = ["mfc_cli"] + cmd
        mfc_cli.main()
    assert e.value.code == 2
