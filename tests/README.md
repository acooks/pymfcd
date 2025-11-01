# Functional Test Suite Design Notes

## Using `subprocess` for Network Setup

During the development and refactoring of the functional test suite (`test_functional.py`), a key decision was made to use direct `subprocess` calls to the `ip` command-line tool for critical network setup and teardown operations, rather than relying exclusively on the `pyroute2.NDB` library.

### Rationale

The primary reason for this choice is **robustness and determinism** within the test environment.

1.  **State Synchronization:** The `pyroute2.NDB` module operates asynchronously. While powerful, this event-driven model proved to be a source of intermittent failures and timeouts in our test fixture. The setup and teardown of a test requires a strict, synchronous sequence of operations. Waiting for `NDB` to detect state changes (like an interface moving to a new namespace) was unreliable and led to race conditions.

2.  **Imperative vs. Declarative:** A test fixture is an imperative process: "do A, then do B, then do C." Direct calls to `ip link set ... netns ...` are blocking and synchronous. They do not return until the operation is complete, guaranteeing the state of the network at each step. This aligns perfectly with the needs of a test fixture.

3.  **Debugging and Simplicity:** Using `subprocess` makes the setup logic explicit and easier to debug. The commands are the same ones a developer would type into a terminal to perform these operations manually, making the test's behavior transparent.

While `pyroute2` is used for some initial setup steps like namespace and veth pair creation, the core, state-critical operations of moving and configuring interfaces are now handled by `subprocess` to ensure the test environment is always in a known, predictable state. This significantly improves the reliability and stability of the functional tests.
