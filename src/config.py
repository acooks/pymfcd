# src/config.py
import configparser
import os

DEFAULT_SOCKET_PATH = "/var/run/mfc_daemon.sock"
DEFAULT_STATE_FILE = "/var/lib/mfc_daemon/state.json"
DEFAULT_SOCKET_GROUP = "root"  # Or a dedicated group like 'mfc_admin'


def load_config(config_path="/etc/mfc_daemon.conf"):
    """
    Loads configuration from the specified path.
    Returns a dictionary with configuration values.
    """
    config = configparser.ConfigParser()

    # Set default values
    settings = {
        "socket_path": DEFAULT_SOCKET_PATH,
        "state_file": DEFAULT_STATE_FILE,
        "socket_group": DEFAULT_SOCKET_GROUP,
    }

    if os.path.exists(config_path):
        try:
            config.read(config_path)
            if "daemon" in config:
                daemon_config = config["daemon"]
                settings["socket_path"] = daemon_config.get(
                    "socket_path", DEFAULT_SOCKET_PATH
                )
                settings["state_file"] = daemon_config.get(
                    "state_file", DEFAULT_STATE_FILE
                )
                settings["socket_group"] = daemon_config.get(
                    "socket_group", DEFAULT_SOCKET_GROUP
                )
        except configparser.Error as e:
            print(f"[WARNING] Could not parse config file at {config_path}: {e}")
            # Proceed with default settings

    return settings
