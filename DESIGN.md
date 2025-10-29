## Design Document: Python Multicast Controller Service (v2 - Reliability Focused)

### 1. Overview & Philosophy

This document outlines the design for a production-grade, service-oriented system to control the Linux kernel's Multicast Forwarding Cache (MFC).

The core design philosophy is **reliability above all else**. A network control plane tool must be predictable, robust, and never leave the system in an inconsistent state. Every design choice is made to build user trust by ensuring that operations are atomic, state is persistent, and failures are handled gracefully. The system provides a user-friendly CLI that abstracts away the complexities of the kernel's legacy multicast API, effectively creating the `ip mroute add` functionality that Linux is missing.

### 2. Architecture

The system maintains a strict client-server architecture to separate the privileged, stateful kernel interactions from the user-facing command logic.

```
+-----------------+      +------------------------+      +-----------------+      +----------------+
|                 |      |                        |      |                 |      |                |
|   mfc_cli.py    |----->|  /var/run/mfc_daemon.sock |----->|  mfc_daemon.py  |----->| Kernel (IPMR)  |
|  (CLI Client)   |      |   (Unix Domain Socket)   |      |   (The Service) |      | (setsockopt)   |
|                 |      |                        |      |                 |      |                |
+-----------------+      +------------------------+      +-----------------+      +----------------+
```

*   **Daemon (`mfc_daemon.py`):** The trusted, long-running service that is the sole owner of the kernel multicast state.
*   **CLI Client (`mfc_cli.py`):** A stateless tool for sending commands to the daemon.
*   **Communication:** Secure and efficient Inter-Process Communication (IPC) via a permission-controlled Unix Domain Socket (UDS).

### 3. The Daemon (`mfc_daemon.py`)

The daemon is the heart of the system, designed for maximum reliability and security.

#### 3.1. Core Responsibilities

*   **Kernel Interaction:**
    *   On startup, opens the raw `IPPROTO_IGMP` socket and calls `MRT_INIT` to take exclusive control of the multicast engine for a specific routing table.
    *   On graceful shutdown (`SIGTERM`), **must** call `MRT_DONE` to cleanly release control and instruct the kernel to tear down all associated VIFs and MFCs. This prevents stale rules from persisting after the service stops.
    *   Contains all `cffi` logic for kernel API interaction.

*   **State Management:**
    *   **Mandatory Persistence:** The daemon's complete state (VIF-to-interface mapping, MFC rules) **must** be persisted to a state file (e.g., `/var/lib/mfc_daemon/state.json`).
    *   **Atomic Writes:** The state file is updated atomically *after* every successful transaction.
    *   **Startup Restore:** On startup, the daemon reads the state file and restores the kernel to the last known-good configuration before accepting any client connections.

*   **Command Handling:**
    *   **Transactional Operations:** All client commands that modify state are treated as atomic transactions. A multi-step operation (e.g., create VIF 1, create VIF 2, add MFC rule) that fails at any point **must** be automatically rolled back to the previous state. This guarantees the system is never left in an inconsistent configuration.
    *   **Strict Input Validation:** The daemon **must** treat all client input as untrusted. A validation layer will rigorously check all parameters (valid IP addresses, existing interface names, correct data types) *before* attempting any kernel operations. Invalid requests are rejected with clear error messages.

*   **IPC Server:**
    *   **Secure UDS:** Creates and listens on a Unix Domain Socket. The path will be configurable via `/etc/mfc_daemon.conf`.
    *   **Strict Permissions:** The daemon will set the UDS file permissions to allow connections only from `root` and members of a dedicated admin group (e.g., `mfc_admin`), preventing unauthorized access.
    *   **Systemd Integration:** The daemon will support `sd_notify` to signal to `systemd` when it has successfully initialized and is ready to accept connections, preventing startup race conditions.

### 4. The CLI Client (`mfc_cli.py`)

The CLI is designed to be intuitive, safe, and script-friendly.

*   **Command Structure:** Provides a simple, `iproute2`-like interface (e.g., `mfc add`, `show`).
*   **Key Features for Reliability:**
    *   **`--dry-run` Flag:** A global flag that instructs the daemon to perform a full validation of the command and report the intended actions without making any changes to the kernel. This is critical for building user trust and safely testing automation.
    *   **`--verbose` / `-v` Flag:** A flag to print the raw JSON request/response, making the client-daemon communication transparent for easy debugging.
    *   **`--output json` Flag:** The `show` command will support this flag to provide machine-readable output, enabling easy integration with scripts and other tools.

### 5. Communication Protocol

The protocol remains a simple JSON request/response model over the UDS, but the payload of error messages will be structured to be more informative.

**Client Request Example:**
```json
{
    "action": "ADD_MFC",
    "dry_run": false,
    "payload": { ... }
}
```

**Daemon Error Response Example:**
```json
{
    "status": "error",
    "error_code": "E_IF_NOT_FOUND",
    "message": "Validation failed: Interface 'eth99' not found."
}
```

### 6. Installation and Service Management

Reliable deployment will be achieved through standard system packaging.

*   **Packaging (`.deb`/`.rpm`):** The project will be distributed as a system package. The package installation script will:
    *   Create a dedicated, non-privileged user and group (e.g., `mfc_daemon`, `mfc_admin`).
    *   Install the daemon and CLI binaries to standard paths (`/usr/local/sbin`, `/usr/local/bin`).
    *   Install a default configuration file at `/etc/mfc_daemon.conf`.
    *   Install and enable the `systemd` unit file.
    *   Set up the state directory (`/var/lib/mfc_daemon`) with correct ownership.

*   **Entrypoint:** A separate script, `src/daemon_main.py`, will serve as the main entrypoint for the daemon. It will handle command-line argument parsing, instantiate the `MfcDaemon` class, and invoke its `main_entrypoint` method.

*   **Configuration:** A simple configuration file will manage key paths:
    ```ini
    # /etc/mfc_daemon.conf
    [daemon]
    socket_path = /var/run/mfc_daemon.sock
    state_file = /var/lib/mfc_daemon/state.json
    socket_group = mfc_admin
    ```

This reliability-focused design ensures the controller is not just a functional tool, but a predictable and robust piece of network infrastructure.
