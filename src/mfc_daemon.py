# src/mfc_daemon.py
import grp
import json
import os
import signal
import socket

from .kernel_ffi import KernelInterface
from .validation import CommandValidator


def get_ifindex(if_name):
    """Helper function to get the index of a network interface."""
    try:
        return socket.if_nametoindex(if_name)
    except OSError:
        raise ValueError(f"Interface '{if_name}' not found.")


class MfcDaemon:
    """
    The main daemon class. Manages the multicast state by translating
    high-level rules into low-level kernel calls.
    """

    def __init__(self):
        self.ki = KernelInterface()
        self.validator = CommandValidator()

        # In-memory state
        # Maps interface names to a dict containing the VIF index and a ref count
        # e.g., {'eth0': {'vifi': 0, 'ref_count': 2}}
        self.vif_map = {}
        # A list of rule dicts: [{"source": "...", "group": "...", "iif": "...",
        # "oifs": [...]}, ...]
        self.mfc_rules = []
        self._running = False

    def add_mfc_rule(self, source, group, iif, oifs):
        """
        Adds a new multicast forwarding rule transactionally.
        If adding the MFC entry fails, any newly created VIFs are rolled back.
        Returns a tuple of (success, message).
        """
        # TODO: Add check for duplicate rule

        # Keep track of interfaces used in this transaction to manage ref_counts
        interfaces_used = [iif] + oifs
        newly_created_vifs = []

        try:
            iif_vifi = self._get_or_create_vif(iif, newly_created_vifs)
            oif_vifis = [
                self._get_or_create_vif(oif, newly_created_vifs) for oif in oifs
            ]

            self.ki._add_mfc(
                source_ip=source, group_ip=group, iif_vifi=iif_vifi, oif_vifis=oif_vifis
            )

            self.mfc_rules.append(
                {"source": source, "group": group, "iif": iif, "oifs": oifs}
            )
            return True, "MFC entry added successfully."
        except Exception as e:
            # Rollback: decrement ref_counts for all interfaces used in this transaction
            # This will also trigger deletion of newly created VIFs
            print("[ROLLBACK] Rolling back VIF changes for transaction.")
            for if_name in interfaces_used:
                self._release_vif(if_name)
            raise e

    def _find_next_vifi(self):
        """Finds the next available VIF index, allowing for reuse of indices."""
        used_vifis = {v["vifi"] for v in self.vif_map.values()}
        for i in range(32):  # MAXVIFS
            if i not in used_vifis:
                return i
        raise RuntimeError("Maximum number of VIFs (32) reached.")

    def _get_or_create_vif(self, if_name, transaction_log=None):
        """
        Gets the VIF index for a given interface name, creating a new VIF
        if one does not already exist, and increments its reference count.
        Logs the creation for transactional rollback.
        """
        if if_name in self.vif_map:
            self.vif_map[if_name]["ref_count"] += 1
            return self.vif_map[if_name]["vifi"]

        vifi = self._find_next_vifi()
        ifindex = get_ifindex(if_name)

        self.ki._add_vif(vifi=vifi, ifindex=ifindex)

        # Add to state
        self.vif_map[if_name] = {"vifi": vifi, "ref_count": 1, "ifindex": ifindex}

        # Log for this transaction
        if transaction_log is not None:
            transaction_log.append((if_name, vifi, ifindex))

        return vifi

    def _release_vif(self, if_name):
        """Decrements the reference count for a VIF and deletes it if unused."""
        if if_name not in self.vif_map:
            print(f"[WARNING] Attempted to release a non-existent VIF: {if_name}")
            return

        self.vif_map[if_name]["ref_count"] -= 1
        if self.vif_map[if_name]["ref_count"] <= 0:
            vifi = self.vif_map[if_name]["vifi"]
            ifindex = self.vif_map[if_name]["ifindex"]
            self.ki._del_vif(vifi=vifi, ifindex=ifindex)
            del self.vif_map[if_name]

    def del_mfc_rule(self, source, group):
        """
        Deletes a multicast forwarding rule.
        Returns a tuple of (success, message).
        """
        try:
            # Find the rule to delete
            rule_to_del = None
            for rule in self.mfc_rules:
                if rule["source"] == source and rule["group"] == group:
                    rule_to_del = rule
                    break

            if not rule_to_del:
                return False, f"Rule for ({source}, {group}) not found."

            self.ki._del_mfc(source_ip=source, group_ip=group)
            self.mfc_rules.remove(rule_to_del)

            # Release the VIFs associated with the rule
            self._release_vif(rule_to_del["iif"])
            for oif in rule_to_del["oifs"]:
                self._release_vif(oif)

            return True, "MFC entry deleted successfully."
        except Exception as e:
            return False, str(e)

    def save_state(self, state_file_path):
        """Saves the current VIF map and MFC rules to a file."""
        state = {"vif_map": self.vif_map, "mfc_rules": self.mfc_rules}
        with open(state_file_path, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self, state_file_path):
        """
        Loads state from a file and re-applies it. This ensures that VIFs
        and reference counts are correctly reconstructed.
        """
        if not os.path.exists(state_file_path):
            print(f"[INFO] State file not found at {state_file_path}. Starting fresh.")
            return

        try:
            with open(state_file_path, "r") as f:
                state = json.load(f)

            # Clear current in-memory state before loading
            self.vif_map.clear()
            self.mfc_rules.clear()

            # Re-apply the rules, which will recreate kernel state (VIFs)
            # and correctly populate the vif_map with ref_counts.
            loaded_rules = state.get("mfc_rules", [])
            print(
                f"[INFO] Found {len(loaded_rules)} rules to re-apply from state file."
            )
            for rule in loaded_rules:
                print(f"[INFO] Re-applying rule: ({rule['source']}, {rule['group']})")
                self.add_mfc_rule(
                    source=rule["source"],
                    group=rule["group"],
                    iif=rule["iif"],
                    oifs=rule["oifs"],
                )

        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to load state from {state_file_path}: {e}")
        except Exception as e:
            print(f"[ERROR] An unexpected error occurred during state load: {e}")

    def run(self, socket_path, socket_group, server_ready_event=None):
        """The main loop of the daemon."""
        self._running = True

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)  # Use a timeout to prevent blocking indefinitely

        try:
            if os.path.exists(socket_path):
                os.unlink(socket_path)

            sock.bind(socket_path)

            # --- Set socket permissions ---
            try:
                gid = grp.getgrnam(socket_group).gr_gid
                os.chown(socket_path, -1, gid)  # -1 means don't change UID
                os.chmod(socket_path, 0o660)  # Read/write for user and group
                print(f"[INFO] Socket group set to '{socket_group}' (gid: {gid})")
            except KeyError:
                print(
                    f"[WARNING] Group '{socket_group}' not found. "
                    "Socket permissions not changed."
                )
            except OSError as e:
                print(f"[WARNING] Could not set socket permissions: {e}")
            # -----------------------------

            sock.listen(1)
            if server_ready_event:
                server_ready_event.set()

            while self._running:
                try:
                    conn, _ = sock.accept()
                    with conn:
                        data = conn.recv(4096)
                        if not data:
                            continue

                        command = json.loads(data.decode("utf-8"))
                        response = self._handle_command(command)
                        conn.sendall(json.dumps(response).encode("utf-8"))
                except socket.timeout:
                    # This is expected, just continue the loop to check self._running
                    continue
        finally:
            sock.close()
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    def stop(self):
        """Stops the main loop gracefully."""
        print("[INFO] Shutdown signal received, stopping loop.")
        self._running = False

    def _signal_handler(self, signum, frame):
        """The actual signal handler that calls the stop method."""
        self.stop()

    def main_entrypoint(self, socket_path, state_file_path, socket_group):
        """
        The main entrypoint for the daemon process. Sets up signal handling,
        loads state, initializes the kernel, runs the main loop, and ensures
        graceful cleanup.
        """
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            # Load initial state
            self.load_state(state_file_path)

            # Initialize kernel interface
            self.ki.mrt_init()

            # Run the main IPC loop
            self.run(socket_path, socket_group)

        finally:
            # Graceful shutdown
            print("[INFO] Cleaning up and shutting down.")
            self.save_state(state_file_path)
            self.ki.mrt_done()

    def _handle_command(self, command):
        """
        Validates a command and dispatches it to the correct method.
        """
        validated_payload, error_message = self.validator.validate(command)

        if error_message:
            return {"status": "error", "message": f"Validation failed: {error_message}"}

        action = command.get("action")
        payload = validated_payload

        try:
            if action == "ADD_MFC":
                success, message = self.add_mfc_rule(
                    source=payload.get("source", "0.0.0.0"),
                    group=payload.get("group"),
                    iif=payload.get("iif"),
                    oifs=payload.get("oifs", []),
                )
                if success:
                    return {
                        "status": "success",
                        "message": (
                            f"MFC entry for ({payload.get('source', '0.0.0.0')}, "
                            f"{payload.get('group')}) added."
                        ),
                    }
                else:
                    return {"status": "error", "message": message}
            elif action == "DEL_MFC":
                success, message = self.del_mfc_rule(
                    source=payload.get("source", "0.0.0.0"),
                    group=payload.get("group"),
                )
                if success:
                    return {
                        "status": "success",
                        "message": (
                            f"MFC entry for ({payload.get('source', '0.0.0.0')}, "
                            f"{payload.get('group')}) deleted."
                        ),
                    }
                else:
                    return {"status": "error", "message": message}
            elif action == "SHOW":
                return {
                    "status": "success",
                    "payload": {
                        "vif_map": self.vif_map,
                        "mfc_rules": self.mfc_rules,
                    },
                }
            else:
                # This case should not be reachable due to validation
                return {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
