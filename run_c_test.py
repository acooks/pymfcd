
import subprocess
import time
import sys
import os
from pyroute2 import IPDB

def run_command(cmd, check=True, capture_output=True):
    print(f"[Orchestrator] Running: ", ' '.join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=capture_output, text=True, check=check)
        if result and result.stdout:
            print(result.stdout.strip())
        if result and result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        if e.stdout: print(f"Stdout:\n{e.stdout}", file=sys.stderr)
        if e.stderr: print(f"Stderr:\n{e.stderr}", file=sys.stderr)
        raise

def main():
    ipdb = IPDB()
    c_tool_process = None
    try:
        # 1. Compile the C test tool
        print("--- Compiling C test tool ---")
        run_command(['gcc', '-o', 'mfc_c_test', 'mfc_c_test.c'])

        # 2. Setup two veth pairs
        print("\n--- Setting up veth interfaces ---")
        ipdb.create(kind='veth', ifname='veth-in', peer='veth-in-peer').commit()
        ipdb.create(kind='veth', ifname='veth-out', peer='veth-out-peer').commit()

        with ipdb.interfaces['veth-in'] as v:
            v.add_ip('192.168.201.1/24')
            v.up()
            v.multicast = 1
            ifindex_in = v.index

        with ipdb.interfaces['veth-out'] as v:
            v.add_ip('192.168.202.1/24')
            v.up()
            v.multicast = 1
            ifindex_out = v.index

        print(f"Interfaces created: veth-in (iif)={ifindex_in}, veth-out (oif)={ifindex_out}")
        time.sleep(1)

        # 3. Run the C tool
        print("\n--- Running C test tool ---")
        c_tool_process = subprocess.Popen(['sudo', './mfc_c_test', str(ifindex_in), str(ifindex_out)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        print("[Orchestrator] Waiting for C tool to configure (2 seconds)...")
        time.sleep(2)

        # 4. Verify the MFC state while C tool is running
        print("\n--- Verifying MFC state with 'ip mroute show' ---")
        mroute_output = run_command(['sudo', 'ip', 'mroute', 'show']).stdout

        expected_route = "(*, 239.1.2.3)"
        iif_route = "Iif: veth-in"
        oif_route = "Oifs: veth-out"

        if expected_route in mroute_output and iif_route in mroute_output and oif_route in mroute_output:
            print("\n[Orchestrator] >>> VERIFICATION SUCCESS <<<")
            print("The expected multicast route was found.")
        else:
            print("\n[Orchestrator] >>> VERIFICATION FAILED <<<", file=sys.stderr)
            print("The expected multicast route was NOT found.", file=sys.stderr)
            print("Full 'ip mroute show' output:", file=sys.stderr)
            print(mroute_output, file=sys.stderr)
            # Check if the C tool failed
            if c_tool_process.poll() is not None:
                stdout, stderr = c_tool_process.communicate()
                print("\nC tool exited prematurely!", file=sys.stderr)
                if stdout: print(f"C tool stdout:\n{stdout}", file=sys.stderr)
                if stderr: print(f"C tool stderr:\n{stderr}", file=sys.stderr)
            raise RuntimeError("MFC entry not found.")

        print("\n[Orchestrator] C tool is holding the route. Waiting for it to exit (8 seconds)...")
        time.sleep(8)

    except Exception as e:
        print(f"\nAn error occurred: {e}", file=sys.stderr)
    finally:
        # 5. Cleanup
        print("\n--- Cleaning up ---")
        if c_tool_process and c_tool_process.poll() is None:
            c_tool_process.terminate()
        
        if 'veth-in' in ipdb.interfaces:
            ipdb.interfaces['veth-in'].remove().commit()
            print("Interface 'veth-in' removed.")
        if 'veth-out' in ipdb.interfaces:
            ipdb.interfaces['veth-out'].remove().commit()
            print("Interface 'veth-out' removed.")
            
        if os.path.exists("mfc_c_test"):
            os.remove("mfc_c_test")
            print("Removed mfc_c_test binary.")
        ipdb.release()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script needs to be run with sudo.", file=sys.stderr)
        sys.exit(1)
    main()
