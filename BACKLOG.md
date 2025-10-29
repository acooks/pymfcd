# Project Backlog: Python Multicast Controller

This document outlines the development tasks required to implement the Python Multicast Controller service, daemon, and CLI. The backlog is broken down by component and prioritized to deliver a functional core first, followed by reliability features and usability enhancements.

---

## Sprint 1: Core Functionality - "Make it Work" (COMPLETED)

**Goal:** Implement the basic, un-mocked, end-to-end workflow. At the end of this sprint, it should be possible to start the daemon and use the CLI to add and remove a real multicast route in the kernel.

### `kernel_ffi.py`
-   [x] **Task 1.1:** Create the `KernelInterface` class.
-   [x] **Task 1.2:** Port the final, working `cffi` C definitions for `vifctl` and `mfcctl` into this class.
-   [x] **Task 1.3:** Implement the `mrt_init()` method to open the raw IGMP socket and call `MRT_INIT`.
-   [x] **Task 1.4:** Implement the `mrt_done()` method to call `MRT_DONE` and close the socket.
-   [x] **Task 1.5:** Implement a private `_add_vif(vifi, ifindex)` method.
-   [x] **Task 1.6:** Implement a private `_add_mfc(source, group, iif_vifi, oif_vifis)` method.
-   [x] **Task 1.7:** Implement corresponding private `_del_vif(vifi, ifindex)` and `_del_mfc(source, group)` methods.

### `mfc_daemon.py` (Core Logic)
-   [x] **Task 1.8:** Create the `MfcDaemon` class.
-   [x] **Task 1.9:** Implement the basic `__init__` method, which instantiates `KernelInterface`.
-   [x] **Task 1.10:** Implement in-memory state management for the VIF map (`{ifname: vifi}`) and MFC rules (list of dicts).
-   [x] **Task 1.11:** Implement the core `add_mfc_rule` method which:
    -   Checks for existing VIFs for the given interface names.
    -   Calls `_add_vif` on the `KernelInterface` for any new interfaces.
    -   Calls `_add_mfc` on the `KernelInterface`.
    -   Updates the internal state maps.
-   [x] **Task 1.12:** Implement a corresponding `del_mfc_rule` method.

### `common.py` (IPC)
-   [x] **Task 1.13:** Implement a simple `send_ipc_command(socket_path, command)` function.
-   [x] **Task 1.14:** Implement the basic daemon-side IPC loop to listen on the UDS, accept a connection, and read one JSON command.

### `mfc_cli.py`
-   [x] **Task 1.15:** Set up `argparse` for the `mfc add`, `mfc del`, and `show` commands with all required arguments.
-   [x] **Task 1.16:** Implement the logic for the `mfc add` command to construct the JSON payload and call `send_ipc_command`.
-   [x] **Task 1.17:** Implement the logic for the `mfc del` command.
-   [x] **Task 1.18:** Implement the logic for the `show` command.

---

## Sprint 2: Reliability & Robustness - "Make it Resilient" (IN PROGRESS)

**Goal:** Implement the critical reliability features from the design document. At the end of this sprint, the daemon should be fault-tolerant, persistent, and secure.

### `mfc_daemon.py` (Reliability)
-   [x] **Task 2.1:** Implement state persistence:
    -   `save_state()` method to atomically write the current VIF map and MFC rules to a JSON file.
    -   `load_state()` method to read the state file on startup and re-apply all rules.
-   [x] **Task 2.2:** Implement transactional logic:
    -   Wrap the `add_mfc_rule` logic in a `try...except` block.
    -   If any kernel call fails, the `except` block must call the appropriate `_del_vif` or `_del_mfc` methods to roll back to the previous state.
-   [x] **Task 2.3:** Implement a robust `SIGTERM` handler that guarantees `mrt_done()` is called for a clean shutdown.
-   [ ] **Task 2.4:** Implement strict input validation for all payloads received from the IPC socket. Reject any malformed or invalid requests *before* attempting kernel operations.

### `config.py` & `common.py`
-   [ ] **Task 2.5:** Implement `load_config()` to read paths and settings from `/etc/mfc_daemon.conf`.
-   [ ] **Task 2.6:** In the daemon, use the loaded config for the UDS path and state file path.
-   [ ] **Task 2.7:** In `common.py`, implement logic for the daemon to set strict file permissions on the UDS.

### Systemd Integration
-   [ ] **Task 2.8:** Write the `mfc_daemon.service` file.
-   [ ] **Task 2.9:** (Optional, Advanced) Implement `sd_notify` support in the daemon to signal readiness to `systemd`.

### Testing
-   [x] **Task T.1:** Create a full end-to-end functional test suite that runs the daemon and CLI in a network namespace.

---

## Sprint 3: User Experience & Polish - "Make it Usable" (NOT STARTED)

**Goal:** Implement the user-facing features that make the tool easy and safe to use.

### `mfc_cli.py` (UX)
-   [ ] **Task 3.1:** Implement the global `--dry-run` flag.
-   [ ] **Task 3.2:** Implement the global `--verbose` flag.
-   [ ] **Task 3.3:** Implement the `--output json` flag for the `show` command.
-   [ ] **Task 3.4:** Improve error reporting to be more user-friendly when a connection to the daemon fails.
-   [ ] **Task 3.5:** Format the `show` command's table output to be clean and well-aligned.

### `mfc_daemon.py` (UX Support)
-   [ ] **Task 3.6:** Implement the logic to handle the `dry_run: true` flag in command payloads, performing all validation but skipping the final kernel calls.

### Packaging
-   [ ] **Task 3.7:** Write a `setup.py` or `pyproject.toml` for the project.
-   [ ] **Task 3.8:** Create a build script or instructions for creating a `.deb` or `.rpm` package. The package should handle file installation, `systemd` service setup, and user/group creation.

---

## Future Sprints / Icebox

-   [ ] **Feature:** Add full IPv6 support.
-   [ ] **Feature:** Implement statistics monitoring and display.
-   [ ] **Feature:** Implement advanced `vif set` commands.
-   [ ] **Refactor:** Convert the daemon's IPC server to use `asyncio`.
-   [ ] **CI/CD:** Set up a continuous integration pipeline to run unit and integration tests automatically.
-   [ ] **Docs:** Write comprehensive Sphinx/MkDocs documentation for the project.
