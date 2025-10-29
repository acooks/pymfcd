# src/mfc_daemon.py
from .kernel_ffi import KernelInterface
import socket
import os
import json
import signal

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
        
        # In-memory state
        # Maps interface names to VIF indices: {'eth0': 0, 'eth1': 1}
        self.vif_map = {}
        # A list of rule dicts: [{"source": "...", "group": "...", "iif": "...", "oifs": [...]}, ...]
        self.mfc_rules = []
        self._next_vifi = 0

    def add_mfc_rule(self, source, group, iif, oifs):
        """
        Adds a new multicast forwarding rule transactionally.
        If adding the MFC entry fails, any newly created VIFs are rolled back.
        """
        # TODO: Add check for duplicate rule
        
        newly_created_vifs = []
        try:
            iif_vifi = self._get_or_create_vif(iif, newly_created_vifs)
            oif_vifis = [self._get_or_create_vif(oif, newly_created_vifs) for oif in oifs]

            self.ki._add_mfc(
                source_ip=source,
                group_ip=group,
                iif_vifi=iif_vifi,
                oif_vifis=oif_vifis
            )
            
            self.mfc_rules.append({
                "source": source, "group": group, "iif": iif, "oifs": oifs
            })
        except Exception:
            # Rollback: delete any VIFs that were created during this failed transaction
            print(f"[ROLLBACK] Deleting {len(newly_created_vifs)} newly created VIFs.")
            for if_name, vifi, ifindex in newly_created_vifs:
                self.ki._del_vif(vifi=vifi, ifindex=ifindex)
                del self.vif_map[if_name]
                self._next_vifi -= 1 # This is a simplification, assumes single-threaded access
            raise # Re-raise the original exception

    def _get_or_create_vif(self, if_name, transaction_log=None):
        """
        Gets the VIF index for a given interface name, creating a new VIF
        if one does not already exist. Logs the creation for transactional rollback.
        """
        if if_name in self.vif_map:
            return self.vif_map[if_name]

        if self._next_vifi >= 32: # MAXVIFS
            raise RuntimeError("Maximum number of VIFs (32) reached.")

        ifindex = get_ifindex(if_name)
        vifi = self._next_vifi
        
        self.ki._add_vif(vifi=vifi, ifindex=ifindex)
        
        # Add to state
        self.vif_map[if_name] = vifi
        self._next_vifi += 1
        
        # Log for this transaction
        if transaction_log is not None:
            transaction_log.append((if_name, vifi, ifindex))
            
        return vifi

    def del_mfc_rule(self, source, group):
        """
        Deletes a multicast forwarding rule.
        """
        # Find the rule to delete
        rule_to_del = None
        for rule in self.mfc_rules:
            if rule["source"] == source and rule["group"] == group:
                rule_to_del = rule
                break
        
        if not rule_to_del:
            raise ValueError(f"Rule for ({source}, {group}) not found.")

        self.ki._del_mfc(source_ip=source, group_ip=group)
        self.mfc_rules.remove(rule_to_del)

    def save_state(self, state_file_path):
        """Saves the current VIF map and MFC rules to a file."""
        state = {
            "vif_map": self.vif_map,
            "mfc_rules": self.mfc_rules
        }
        with open(state_file_path, 'w') as f:
            json.dump(state, f, indent=2)

    def load_state(self, state_file_path):
        """Loads state from a file and re-applies it."""
        if not os.path.exists(state_file_path):
            print(f"[INFO] State file not found at {state_file_path}. Starting fresh.")
            return

        try:
            with open(state_file_path, 'r') as f:
                state = json.load(f)
            
            # Restore internal state first
            self.vif_map = state.get("vif_map", {})
            # Ensure _next_vifi is correctly updated
            if self.vif_map:
                self._next_vifi = max(self.vif_map.values()) + 1
            
            # Re-apply the rules, which will recreate kernel state
            # and also repopulate self.mfc_rules
            loaded_rules = state.get("mfc_rules", [])
            for rule in loaded_rules:
                print(f"[INFO] Re-applying rule: ({rule['source']}, {rule['group']})")
                self.add_mfc_rule(
                    source=rule["source"],
                    group=rule["group"],
                    iif=rule["iif"],
                    oifs=rule["oifs"]
                )

        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to load state from {state_file_path}: {e}")
        except Exception as e:
            print(f"[ERROR] An unexpected error occurred during state load: {e}")

    def run(self, socket_path, server_ready_event=None):
        """The main loop of the daemon."""
        self._running = True
        
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5) # Use a timeout to prevent blocking indefinitely
        
        try:
            if os.path.exists(socket_path):
                os.unlink(socket_path)

            sock.bind(socket_path)
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
                        
                        command = json.loads(data.decode('utf-8'))
                        response = self._handle_command(command)
                        conn.sendall(json.dumps(response).encode('utf-8'))
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

    def main_entrypoint(self, socket_path, state_file_path, server_ready_event=None):
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
            self.run(socket_path, server_ready_event)

        finally:
            # Graceful shutdown
            print("[INFO] Cleaning up and shutting down.")
            self.save_state(state_file_path)
            self.ki.mrt_done()

    def _handle_command(self, command):
        """Parses a command and dispatches it to the correct method."""
        action = command.get("action")
        payload = command.get("payload", {})

        try:
            if action == "ADD_MFC":
                self.add_mfc_rule(
                    source=payload.get("source", "0.0.0.0"),
                    group=payload.get("group"),
                    iif=payload.get("iif"),
                    oifs=payload.get("oifs", []),
                )
                return {"status": "success"}
            elif action == "DEL_MFC":
                self.del_mfc_rule(
                    source=payload.get("source", "0.0.0.0"),
                    group=payload.get("group"),
                )
                return {"status": "success"}
            elif action == "SHOW":
                return {
                    "status": "success",
                    "payload": {
                        "vif_map": self.vif_map,
                        "mfc_rules": self.mfc_rules,
                    }
                }
            else:
                return {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
