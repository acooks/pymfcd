# tests/test_config.py

from src.config import (
    DEFAULT_SOCKET_GROUP,
    DEFAULT_SOCKET_PATH,
    DEFAULT_STATE_FILE,
    load_config,
)


# Test case 1: Config file does not exist
def test_load_config_no_file(tmp_path):
    config_path = tmp_path / "non_existent_config.conf"
    settings = load_config(str(config_path))
    assert settings["socket_path"] == DEFAULT_SOCKET_PATH
    assert settings["state_file"] == DEFAULT_STATE_FILE
    assert settings["socket_group"] == DEFAULT_SOCKET_GROUP


# Test case 2: Config file exists but is empty
def test_load_config_empty_file(tmp_path):
    config_path = tmp_path / "empty_config.conf"
    config_path.touch()  # Create an empty file
    settings = load_config(str(config_path))
    assert settings["socket_path"] == DEFAULT_SOCKET_PATH
    assert settings["state_file"] == DEFAULT_STATE_FILE
    assert settings["socket_group"] == DEFAULT_SOCKET_GROUP


# Test case 3: Config file exists but is invalid (malformed INI)
def test_load_config_invalid_file(tmp_path, capsys):
    config_path = tmp_path / "invalid_config.conf"
    config_path.write_text("this is not valid ini format")
    settings = load_config(str(config_path))

    # Check that a warning was printed
    captured = capsys.readouterr()
    assert "[WARNING] Could not parse config file" in captured.out

    # Should still return default settings
    assert settings["socket_path"] == DEFAULT_SOCKET_PATH
    assert settings["state_file"] == DEFAULT_STATE_FILE
    assert settings["socket_group"] == DEFAULT_SOCKET_GROUP


# Test case 4: Config file exists but without [daemon] section
def test_load_config_no_daemon_section(tmp_path):
    config_path = tmp_path / "no_daemon_section.conf"
    config_path.write_text(
        """
[other_section]
key=value
"""
    )
    settings = load_config(str(config_path))
    assert settings["socket_path"] == DEFAULT_SOCKET_PATH
    assert settings["state_file"] == DEFAULT_STATE_FILE
    assert settings["socket_group"] == DEFAULT_SOCKET_GROUP


# Test case 5: Config file exists with [daemon] section but missing some keys
def test_load_config_missing_keys(tmp_path):
    config_path = tmp_path / "missing_keys.conf"
    config_path.write_text(
        """
[daemon]
socket_path = /tmp/custom.sock
"""
    )
    settings = load_config(str(config_path))
    assert settings["socket_path"] == "/tmp/custom.sock"
    assert settings["state_file"] == DEFAULT_STATE_FILE
    assert settings["socket_group"] == DEFAULT_SOCKET_GROUP


# Test case 6: Config file exists and is valid, with all keys present
def test_load_config_valid_file(tmp_path):
    config_path = tmp_path / "valid_config.conf"
    config_content = """
[daemon]
socket_path = /var/run/my_mfc_daemon.sock
state_file = /var/lib/my_mfc_daemon/my_state.json
socket_group = my_group
"""
    config_path.write_text(config_content)
    settings = load_config(str(config_path))
    assert settings["socket_path"] == "/var/run/my_mfc_daemon.sock"
    assert settings["state_file"] == "/var/lib/my_mfc_daemon/my_state.json"
    assert settings["socket_group"] == "my_group"
