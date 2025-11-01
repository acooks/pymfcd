# Python Multicast Forwarding Controller Service

This project implements a simple controller for the Linux kernel multicast forwarding cache (MFC entries). It enables a configuration of "static multicast joins".

This Python-based daemon interacts with the kernel's legacy `setsockopt` API and a command-line interface (CLI) client for user interaction.

## Table of Contents

1.  [Introduction](#1-introduction)
2.  [Architecture](#2-architecture)
    - [Daemon (`mfc_daemon.py`)](#daemon-mfc_daemonpy)
    - [CLI Client (`mfc_cli.py`)](#cli-client-mfc_clipy)
    - [Communication Protocol](#communication-protocol)
3.  [Features](#3-features)
4.  [Installation](#4-installation)
    - [Prerequisites](#prerequisites)
    - [Systemd Service (Recommended)](#systemd-service-recommended)
5.  [Usage](#5-usage)
    - [CLI Examples](#cli-examples)
6.  [Development](#6-development)
    - [Code Style and Quality](#code-style-and-quality)
    - [Running the Test Suites](#running-the-test-suites)
7.  [Kernel Interaction Details](#7-kernel-interaction-details)
8.  [Contributing](#8-contributing)
9.  [License](#9-license)

---

## 1. Introduction

This project provides a controller for managing Multicast Forwarding Cache (MFC) entries in the Linux kernel. It directly addresses the absence of a direct `ip mroute add` command within the standard `iproute2` utility.

The reason for this missing command is historical. The kernel's multicast control interface is a legacy `setsockopt`-based API that predates the modern `netlink` interface used by `iproute2` for most other routing functions. This older API is complex, requiring careful data structure manipulation and a stateful, persistent connection.

A key characteristic of this kernel interface is that the multicast routing state is maintained only as long as the userspace application that initialized it remains active and keeps the socket open. Termination of this application results in the automatic removal of all associated MFC entries.

To meet this requirement, the project implements a persistent daemon (`mfc_daemon.py`) that encapsulates the complexities of the kernel API. A command-line interface (`mfc_cli.py`) provides a mechanism for user interaction with the daemon.

### Use Cases

This software serves the following primary applications:

1.  **Multicast Test Environment:** Facilitates the creation of static multicast routes for testing and development purposes, bypassing the need for dynamic routing protocols such as PIM or IGMP.

2.  **Kernel Interface Study:** Offers a functional and tested reference implementation for understanding the Linux kernel's multicast `setsockopt` API, including aspects like C structure definitions, data packing, and the requirement for a persistent userspace component.

## 2. Architecture

The system is designed with a clear separation of concerns, consisting of a long-running daemon and a lightweight command-line client.

```dot
digraph Architecture {
    rankdir=LR;
    node [shape=box, style="rounded,filled", fillcolor=lightblue, fontname="Helvetica"];
    edge [fontname="Helvetica"];

    user [label="User", shape=none, fillcolor=none];
    cli [label="mfc_cli.py\n(CLI Client)"];
    uds [label="/var/run/mfc_daemon.sock\n(Unix Domain Socket)"];
    daemon [label="mfc_daemon.py\n(The Service)"];
    kernel [label="Kernel (IPMR)\n(setsockopt)"];

    user -> cli [label=" issues commands"];
    cli -> uds;
    uds -> daemon;
    daemon -> kernel;
}
```

### Daemon (`mfc_daemon.py`)

The daemon is the core component, responsible for all low-level kernel interactions.

- **Kernel Interaction:** Opens the raw `IPPROTO_IGMP` socket, calls `MRT_INIT`, and manages VIFs (`MRT_ADD_VIF`, `MRT_DEL_VIF`) and MFC rules (`MRT_ADD_MFC`, `MRT_DEL_MFC`) using `cffi`.
- **State Management:** Maintains an in-memory representation of all active VIFs (mapping interface names to VIF indices) and MFC rules.
- **IPC Server:** Creates and listens on a Unix Domain Socket (UDS) at `/var/run/mfc_daemon.sock` for commands from the CLI client.
- **Command Handling:** Parses JSON commands from the client, translates them into `setsockopt` calls, and handles all necessary `cffi` structure manipulation (including padding and endianness).
- **Persistence (Optional):** Can be extended to save/load its state to a configuration file (e.g., `/etc/mfc_daemon/state.json`) for persistence across reboots.

### CLI Client (`mfc_cli.py`)

The CLI client is the user-facing interface, designed for ease of use.

- **Command Parsing:** Uses `argparse` to provide a subcommand structure (e.g., `mfc add`, `mfc del`, `show`).
- **IPC Client:** Connects to the daemon's UDS, sends JSON commands, and receives JSON responses.
- **User Feedback:** Displays clear success/error messages and formats daemon responses (e.g., `show` output) into human-readable tables.

### Communication Protocol

Client-daemon communication uses JSON over a Unix Domain Socket.

### Design Choices

- **Client-Server Model:** This architecture decouples the user-facing CLI from the core logic that interacts with the kernel. This is essential because the kernel requires the process that initializes multicast routing to remain alive; the daemon fulfills this role, while allowing for multiple, short-lived CLI clients.

- **Unix Domain Socket (UDS):** UDS was chosen for Inter-Process Communication (IPC) as it is more secure and efficient for local communication than TCP sockets. Filesystem permissions can be used to control which users can access the socket and send commands to the daemon.

- **`cffi` for FFI:** The `cffi` library is used to interact with the kernel's C-level API. This approach was chosen over a traditional C extension because it allows the project to be pure Python (with `cffi` as a dependency), which simplifies packaging, distribution, and installation, as users do not need a C compiler on their system.

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

- **Programmatic MFC Control:** Add and delete multicast forwarding rules.
- **VIF Abstraction:** Users interact with interface names; the daemon handles VIF index assignment and lifecycle.
- **Robust Kernel Interaction:** Uses `cffi` to correctly interface with the kernel's legacy `setsockopt` API, handling complex C structure details (padding, endianness).
- **Client-Server Architecture:** Clean separation of concerns for daemon persistence and CLI usability.
- **Unix Domain Socket IPC:** Secure and efficient inter-process communication.
- **State Persistence:** Daemon state (MFC rules) is saved and loaded for persistence across reboots, with VIFs dynamically reconstructed.
- **VIF Reference Counting:** VIFs are automatically added and removed from the kernel based on their usage by MFC rules, preventing resource leaks.
- **Intuitive CLI:** `iproute2`-like command structure for ease of use.
- **State Display:** `show` command to view current MFC and VIF state (currently raw JSON, future improvement planned).

## 4. Installation

### Prerequisites

- **Python 3.x**
- **`cffi` library:** `pip install cffi`
- **`pyroute2` library:** `pip install pyroute2`
- **`jsonschema` library:** `pip install jsonschema`
- **`pytest` library:** `pip install pytest` (for running tests)
- **`make` utility:** For service management.
- **Root privileges:** Required for all kernel-level network operations and service installation.

### Systemd Service Installation (Recommended)

To install the `mfc_daemon` as a Systemd service, use the provided `Makefile`.
This will:

1.  Create a dedicated `mfc-daemon` system group if it doesn't already exist.
2.  Copy the `mfc_daemon.service` file to `/etc/systemd/system/`.
3.  Reload the Systemd daemon and enable the service to start on boot.

```bash
cd /path/to/mfc-controller
sudo make install-service
```

After installation, you can manage the service using `make` commands:

- **Start the daemon:**
  ```bash
  sudo make start-service
  ```
- **Stop the daemon:**
  ```bash
  sudo make stop-service
  ```
- **Check daemon status:**
  ```bash
  sudo make status-service
  ```
- **Uninstall the service:**
  ```bash
  sudo make uninstall-service
  ```

## 5. Usage

Once the `mfc_daemon` is running as a Systemd service, you can interact with it using the `mfc_cli` client. All CLI commands require `sudo`.

### CLI Examples

**1. Show current multicast forwarding state:**

```bash
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli show
# Expected output (example - actual output is raw JSON):
# {
#   "status": "success",
#   "payload": {
#     "vif_map": {},
#     "mfc_rules": []
#   }
# }
```

**2. Add a multicast route:**

This example adds a rule for source `10.0.1.10` and group `239.10.20.30`,
with incoming interface `veth-in-p` and outgoing interface `veth-out-p`.

```bash
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli mfc add \
    --source 10.0.1.10 \
    --group 239.10.20.30 \
    --iif veth-in-p \
    --oifs veth-out-p
# Expected output:
# {
#   "status": "success",
#   "message": "MFC entry for (10.0.1.10, 239.10.20.30) added."
# }
```

**3. Add another multicast route using an existing interface:**

This demonstrates VIF reference counting. `veth-in-p` will not create a new VIF.

```bash
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli mfc add \
    --source 10.0.1.11 \
    --group 239.10.20.31 \
    --iif veth-in-p \
    --oifs eth0
```

**4. Show state after adding rules:**

```bash
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli show
# Expected output (example - actual output is raw JSON):
# {
#   "status": "success",
#   "payload": {
#     "vif_map": {
#       "veth-in-p": {"vifi": 0, "ref_count": 2, "ifindex": <idx>},
#       "veth-out-p": {"vifi": 1, "ref_count": 1, "ifindex": <idx>},
#       "eth0": {"vifi": 2, "ref_count": 1, "ifindex": <idx>}
#     },
#     "mfc_rules": [
#       {"source": "10.0.1.10", "group": "239.10.20.30", "iif": "veth-in-p", "oifs": ["veth-out-p"]},
#       {"source": "10.0.1.11", "group": "239.10.20.31", "iif": "veth-in-p", "oifs": ["eth0"]}
#     ]
#   }
# }
```

**5. Delete a multicast route:**

```bash
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli mfc del \
    --source 10.0.1.10 \
    --group 239.10.20.30
# Expected output:
# {
#   "status": "success",
#   "message": "MFC entry for (10.0.1.10, 239.10.20.30) deleted."
# }
```

**6. Show state after deleting a rule:**

Note that `veth-out-p` will be removed from `vif_map` as its ref count drops to 0.

```bash
sudo "PYTHONPATH=$(pwd)" python3 -m src.mfc_cli show
# Expected output (example - actual output is raw JSON):
# {
#   "status": "success",
#   "payload": {
#     "vif_map": {
#       "veth-in-p": {"vifi": 0, "ref_count": 1, "ifindex": <idx>},
#       "eth0": {"vifi": 2, "ref_count": 1, "ifindex": <idx>}
#     },
#     "mfc_rules": [
#       {"source": "10.0.1.11", "group": "239.10.20.31", "iif": "veth-in-p", "oifs": ["eth0"]}
#     ]
#   }
# }
```

## 6. Development

### Code Style and Quality

This project adheres to strict code style and quality standards enforced by `black` for formatting and `ruff` for linting.

- **Black (Code Formatter):** Used to ensure consistent code formatting across the entire project.
  ```bash
  pip install black
  black .
  ```
- **Ruff (Linter):** Used to enforce code quality, identify potential bugs, and ensure adherence to best practices.
  ```bash
  pip install ruff
  ruff check .
  ruff format .
  ```

It is recommended to run these tools before submitting any changes to ensure consistency.

### Running the Test Suites

- **Unit Tests:**
  ```bash
  python3 -m pytest tests/
  ```
- **Functional Test (requires sudo):**
  ```bash
  sudo "PYTHONPATH=$(pwd)" python3 -m pytest tests/test_functional.py
  ```

## 7. Kernel Interaction Details

Interacting with the kernel's legacy multicast API from Python presents several non-obvious challenges. This project serves as a reference for handling them correctly.

- **Two-API Reality:** The Linux kernel's network control plane has evolved. The multicast routing API is a legacy `setsockopt`-based system, predating the modern `netlink` interface. While `iproute2` utilizes `netlink` for most routing functions and for _reading_ multicast state (`ip mroute show`), it does not provide `netlink`-based commands or an implementation for _writing_ (adding or deleting) MFC entries. This is because the kernel's `setsockopt` API for multicast requires the application that opens the socket to maintain a persistent connection for the routes to remain active. A stateless command like `ip mroute add` would result in routes immediately disappearing upon command completion, rendering it impractical. This fundamental design choice necessitates a persistent userspace application to manage MFC state.

- **`cffi` for FFI:** The `cffi` library is used to bridge Python and C. It allows us to define the necessary C structures (`vifctl`, `mfcctl`) in a Python string and call the `setsockopt` function from `libc` directly. This avoids the need for a separate C extension module, making the project easier to distribute.

- **Structure Padding:** C compilers insert padding into structures to ensure that fields are aligned on memory addresses that are multiples of their size. This is critical for performance on many CPU architectures. When we define `struct mfcctl` in `cffi`, we must manually add a `char _padding[2]` field to replicate the padding the C compiler would add. Without this, the structure's memory layout in our Python application would not match what the kernel expects, leading to errors.

- **Endianness:** IP addresses in C structures must be in network byte order (big-endian). However, modern CPUs are typically little-endian. When `cffi` writes an integer to a struct field, it writes it in the host's byte order. To handle this, we must "pre-swap" the byte order in Python before giving the integer to `cffi`. The expression `int.from_bytes(socket.inet_aton(ip_str), 'little')` accomplishes this: `socket.inet_aton()` converts the IP string to a big-endian byte string, and `int.from_bytes(..., 'little')` then interprets those big-endian bytes as a little-endian integer. When `cffi` writes this "pre-swapped" integer to memory using little-endian byte order, the original big-endian byte sequence is restored, which is what the kernel requires.

- **Daemon Requirement:** As mentioned in the introduction, the `MRT_INIT` call ties the kernel's multicast routing state to the file descriptor of the socket that enabled it. When that socket is closed (i.e., the process terminates), the kernel cleans up all VIFs and MFCs created by that process. This is the fundamental reason a persistent daemon is required.

- **VIF Prerequisites:** Before a VIF can be created, the underlying physical interface must have the `IFF_MULTICAST` flag enabled. This is standard for Ethernet interfaces but may need to be explicitly enabled on other interface types.

## 8. Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## 9. License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
