# Python Multicast Forwarding Controller Service

This project implements a user-friendly, service-oriented solution for programming Linux kernel multicast forwarding rules (MFC entries). It addresses the lack of a direct `ip mroute add` command in `iproute2` by providing a Python-based daemon that interacts with the kernel's legacy `setsockopt` API and a command-line interface (CLI) client for user interaction.

## Table of Contents

1.  [Introduction](#1-introduction)
2.  [Architecture](#2-architecture)
    *   [Daemon (`mfc_daemon.py`)](#daemon-mfc_daemonpy)
    *   [CLI Client (`mfc_cli.py`)](#cli-client-mfc_clipy)
    *   [Communication Protocol](#communication-protocol)
3.  [Features](#3-features)
4.  [Installation](#4-installation)
    *   [Prerequisites](#prerequisites)
    *   [Setup](#setup)
    *   [Systemd Service (Recommended)](#systemd-service-recommended)
5.  [Usage](#5-usage)
    *   [Daemon Management](#daemon-management)
    *   [CLI Examples](#cli-examples)
6.  [Kernel Interaction Details](#6-kernel-interaction-details)
7.  [Contributing](#7-contributing)
8.  [License](#8-license)

---

## 1. Introduction

The Linux kernel's multicast routing capabilities are powerful but expose a challenging API for userspace applications. While `ip mroute show` can display multicast forwarding entries, there's no direct `ip mroute add` command. Programming these entries requires using the legacy `setsockopt` API on a raw `IPPROTO_IGMP` socket, a task fraught with complexities like C structure padding and byte-endianness issues when using Foreign Function Interfaces (FFI) from Python.

This project provides a robust solution by encapsulating these complexities within a dedicated daemon and exposing a simple, intuitive CLI.

## 2. Architecture

The system is designed with a clear separation of concerns, consisting of a long-running daemon and a lightweight command-line client.

```
+-----------------+      +------------------------+      +-----------------+      +----------------+
|                 |      |                        |      |                 |      |                |
|   mfc_cli.py    |----->|  /var/run/mfc_daemon.sock |----->|  mfc_daemon.py  |----->| Kernel (IPMR)  |
|  (CLI Client)   |      |   (Unix Domain Socket)   |      |   (The Service) |      | (setsockopt)   |
|                 |      |                        |      |                 |      |                |
+-----------------+      +------------------------+      +-----------------+      +----------------+
       ^                                                          |
       |                                                          |
       +----------------------------------------------------------+
                  (User commands via command line)
```

### Daemon (`mfc_daemon.py`)

The daemon is the core component, responsible for all low-level kernel interactions.

*   **Kernel Interaction:** Opens the raw `IPPROTO_IGMP` socket, calls `MRT_INIT`, and manages VIFs (`MRT_ADD_VIF`, `MRT_DEL_VIF`) and MFC rules (`MRT_ADD_MFC`, `MRT_DEL_MFC`) using `cffi`.
*   **State Management:** Maintains an in-memory representation of all active VIFs (mapping interface names to VIF indices) and MFC rules.
*   **IPC Server:** Creates and listens on a Unix Domain Socket (UDS) at `/var/run/mfc_daemon.sock` for commands from the CLI client.
*   **Command Handling:** Parses JSON commands from the client, translates them into `setsockopt` calls, and handles all necessary `cffi` structure manipulation (including padding and endianness).
*   **Persistence (Optional):** Can be extended to save/load its state to a configuration file (e.g., `/etc/mfc_daemon/state.json`) for persistence across reboots.

### CLI Client (`mfc_cli.py`)

The CLI client is the user-facing interface, designed for ease of use.

*   **Command Parsing:** Uses `argparse` to provide a subcommand structure (e.g., `mfc add`, `mfc del`, `show`).
*   **IPC Client:** Connects to the daemon's UDS, sends JSON commands, and receives JSON responses.
*   **User Feedback:** Displays clear success/error messages and formats daemon responses (e.g., `show` output) into human-readable tables.

### Communication Protocol

Client-daemon communication uses JSON over a Unix Domain Socket.

**Client Request Example:**
```json
{
    "action": "ADD_MFC",
    "payload": {
        "source": "10.1.1.5",
        "group": "239.10.20.30",
        "iif": "eth1",
        "oifs": ["eth2", "eth3"]
    }
}
```

**Daemon Response (Success) Example:**
```json
{
    "status": "success",
    "message": "MFC entry for (10.1.1.5, 239.10.20.30) added."
}
```

**Daemon Response (Error) Example:**
```json
{
    "status": "error",
    "message": "Invalid argument: Interface 'eth99' not found."
}
```

## 3. Features

*   **Programmatic MFC Control:** Add and delete multicast forwarding rules.
*   **VIF Abstraction:** Users interact with interface names; the daemon handles VIF index assignment.
*   **Robust Kernel Interaction:** Uses `cffi` to correctly interface with the kernel's legacy `setsockopt` API, handling complex C structure details (padding, endianness).
*   **Client-Server Architecture:** Clean separation of concerns for daemon persistence and CLI usability.
*   **Unix Domain Socket IPC:** Secure and efficient inter-process communication.
*   **Intuitive CLI:** `iproute2`-like command structure for ease of use.
*   **State Display:** `show` command to view current MFC and VIF state.

## 4. Setup (Development Environment)

### Prerequisites

*   **Python 3.x**
*   **`cffi` library:** `pip install cffi`
*   **`pyroute2` library:** `pip install pyroute2`
*   **`pytest` library:** `pip install pytest` (for running tests)
*   **Root privileges:** Required for all kernel-level network operations.

### Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-repo/mfc-controller.git # Replace with actual repo URL
    cd mfc-controller
    ```
2.  **Install Python dependencies:**
    ```bash
    pip install cffi pyroute2 pytest
    ```

### Code Style and Quality

This project adheres to strict code style and quality standards enforced by `black` for formatting and `ruff` for linting.

*   **Black (Code Formatter):** Used to ensure consistent code formatting across the entire project.
    ```bash
    pip install black
    black .
    ```
*   **Ruff (Linter):** Used to enforce code quality, identify potential bugs, and ensure adherence to best practices.
    ```bash
    pip install ruff
    ruff check .
    ruff format .
    ```

It is recommended to run these tools before submitting any changes to ensure consistency.

## 5. Usage

All commands must be run from the root of the project directory and require root privileges.

### Running the Daemon

To run the daemon, execute the `daemon_main` module. It will run in the foreground, listen for commands, and print log messages to the console.

```bash
# Start the daemon in a terminal
sudo "PYTHONPATH=$(pwd)" python3 -m src.daemon_main
```

### Using the CLI

In a separate terminal, you can use the `mfc_cli` module to interact with the running daemon.

```bash
# Show current state (will be empty initially)
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli show

# Add a multicast route (e.g., for the loopback interface 'lo')
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli mfc add --group 239.1.2.3 --iif lo --oifs lo

# Show the new state
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli show

# Delete the route
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli mfc del --group 239.1.2.3
```

### Running the Test Suites

*   **Unit Tests:**
    ```bash
    python3 -m pytest tests/
    ```
*   **Functional Test (requires sudo):**
    ```bash
    sudo "PYTHONPATH=$(pwd)" python3 -m pytest tests/test_functional.py
    ```

## 6. Kernel Interaction Details

This project leverages the following key insights from our deep dive into Linux multicast:

*   **Two-API Reality:** The kernel uses the legacy `setsockopt` API for *writing* MFC entries and the modern `rtnetlink` API (used by `ip mroute show`) for *reading* them.
*   **`cffi` for FFI:** The `cffi` library is used to bridge Python and C, allowing direct calls to `setsockopt`.
*   **Structure Padding:** The `struct mfcctl` requires explicit `char _padding[2]` in its `cffi` definition to match the C compiler's memory layout.
*   **Endianness:** On a little-endian host, `int.from_bytes(socket.inet_aton(...), 'little')` is used to create the "pre-swapped" integer that `cffi` writes to memory, resulting in the correct big-endian (network byte order) required by the kernel.
*   **Daemon Requirement:** The kernel's multicast state is tied to the lifecycle of the process that initializes it, necessitating a persistent daemon.
*   **VIF Prerequisites:** Underlying interfaces must have `IFF_MULTICAST` enabled and VIFs must be bound to a valid local IP address or interface index.

## 7. Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## 8. License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
