#!/usr/bin/env python3
#
# Gemini CLI Tool Logic: commit_logic.sh
#
# This script is executed by the 'callCommand'. It reads a JSON object
# from stdin, parses it to extract the commit message, and then performs
# the git commit.

import sys
import json
import subprocess
import signal

# Define a handler for the timeout
def handle_timeout(signum, frame):
    raise TimeoutError("Timeout expired while waiting for stdin")

def main():
    try:
        # Set the signal handler and a 5-second alarm
        signal.signal(signal.SIGALRM, handle_timeout)
        signal.alarm(5)

        # Read the entire standard input
        try:
            input_data = sys.stdin.read()
        finally:
            # Disable the alarm
            signal.alarm(0)

        if not input_data:
            print("Error: No data received from stdin.", file=sys.stderr)
            sys.exit(1)

        # Parse the JSON object
        tool_call = json.loads(input_data)

        # Extract the 'message' argument
        commit_message = tool_call.get("message")
        if not commit_message:
            print("Error: 'message' argument not found in JSON input.", file=sys.stderr)
            sys.exit(1)

        # Commit using the message. We pipe the message to git's stdin
        # to avoid any shell interpretation issues.
        subprocess.run(
            ["git", "commit", "--file=-"],
            input=commit_message,
            text=True,
            check=True
        )

        print("Commit successful.")

    except TimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from stdin.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error during git operation: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
