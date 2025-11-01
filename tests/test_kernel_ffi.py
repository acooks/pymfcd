# tests/test_kernel_ffi.py
import socket
from unittest.mock import MagicMock, patch

import pytest

from src.kernel_ffi import (
    IPPROTO_IGMP,
    IPPROTO_IP,
    MRT_ADD_MFC,
    MRT_ADD_VIF,
    MRT_DEL_MFC,
    MRT_DEL_VIF,
    MRT_DONE,
    MRT_INIT,
    VIFF_USE_IFINDEX,
    KernelInterface,
)


def test_kernel_interface_initialization_and_struct_sizes():
    """
    Tests that the KernelInterface class can be instantiated and that
    the CFFI structures have the correct, expected sizes, including padding.
    This is the foundational test to ensure the C ABI is correctly represented.
    """
    ki = KernelInterface()
    assert ki.ffi is not None
    assert ki.libc is not None

    # Verify the size of the mfcctl struct.
    # This is a critical test to ensure our padding definition is correct.
    # The C compiler adds 2 bytes of padding, making the total size 60.
    assert ki.ffi.sizeof("struct mfcctl") == 60

    # Verify the size of the vifctl struct.
    # vifi(2) + flags(1) + threshold(1) + rate_limit(4) + union(4) + rmt_addr(4) = 16
    # The structure is naturally aligned, so no padding is expected.
    assert ki.ffi.sizeof("struct vifctl") == 16


def test_mrt_init_success():
    """
    Tests that mrt_init() correctly opens a socket and calls MRT_INIT.
    """
    # We patch the socket call to avoid creating a real socket
    with patch("socket.socket") as mock_socket_constructor:
        mock_sock_instance = MagicMock()
        mock_sock_instance.fileno.return_value = 5  # a dummy file descriptor
        mock_socket_constructor.return_value = mock_sock_instance

        ki = KernelInterface()
        # Mock the C library calls
        ki.libc = MagicMock()
        ki.libc.setsockopt.return_value = 0

        ki.mrt_init()

        # Assert socket was created correctly
        mock_socket_constructor.assert_called_once_with(
            socket.AF_INET, socket.SOCK_RAW, IPPROTO_IGMP
        )
        assert ki.sock is not None

        # Assert setsockopt was called correctly for MRT_INIT
        ki.libc.setsockopt.assert_called_once()
        args, _ = ki.libc.setsockopt.call_args
        assert args[0] == 5  # fileno
        assert args[1] == IPPROTO_IP
        assert args[2] == MRT_INIT
        # args[3] is a cdata pointer to an int with value 1
        assert isinstance(args[3], type(ki.ffi.new("int*")))
        assert args[3][0] == 1
        assert args[4] == ki.ffi.sizeof("int")


def test_mrt_init_failure_raises_oserror():
    """
    Tests that mrt_init() raises an OSError if the setsockopt call fails.
    """
    with patch("socket.socket"):
        ki = KernelInterface()
        ki.libc = MagicMock()
        ki.libc.setsockopt.return_value = -1  # Simulate failure
        ki.ffi.errno = 1  # EPERM (Permission denied)

        with pytest.raises(OSError, match=r"\[MRT_INIT\] Operation not permitted"):
            ki.mrt_init()


def test_mrt_done_success():
    """
    Tests that mrt_done() correctly calls MRT_DONE and closes the socket.
    """
    with patch("socket.socket") as mock_socket_constructor:
        mock_sock_instance = MagicMock()
        mock_sock_instance.fileno.return_value = 5
        mock_socket_constructor.return_value = mock_sock_instance

        ki = KernelInterface()
        ki.libc = MagicMock()
        ki.libc.setsockopt.return_value = 0
        ki.sock = mock_sock_instance  # Manually set the mock socket

        ki.mrt_done()

        # Assert setsockopt was called correctly for MRT_DONE
        ki.libc.setsockopt.assert_called_once()
        args, _ = ki.libc.setsockopt.call_args
        assert args[0] == 5
        assert args[1] == IPPROTO_IP
        assert args[2] == MRT_DONE
        assert args[3][0] == 1
        assert args[4] == ki.ffi.sizeof("int")

        # Assert socket was closed
        mock_sock_instance.close.assert_called_once()
        assert ki.sock is None


def test_mrt_done_failure_raises_oserror():
    """
    Tests that mrt_done() raises an OSError if the setsockopt call fails.
    """
    with patch("socket.socket") as mock_socket_constructor:
        mock_sock_instance = MagicMock()
        mock_sock_instance.fileno.return_value = 5
        mock_socket_constructor.return_value = mock_sock_instance

        ki = KernelInterface()
        ki.libc = MagicMock()
        ki.libc.setsockopt.return_value = -1
        ki.ffi.errno = 1  # EPERM
        ki.sock = mock_sock_instance

        with pytest.raises(OSError, match=r"\[MRT_DONE\] Operation not permitted"):
            ki.mrt_done()

        # Even on failure, the socket should still be closed
        mock_sock_instance.close.assert_called_once()
        assert ki.sock is None


def test_add_vif_success():
    """
    Tests that _add_vif correctly populates a vifctl struct and calls
    setsockopt with MRT_ADD_VIF.
    """
    ki = KernelInterface()
    ki.libc = MagicMock()
    ki.libc.setsockopt.return_value = 0
    ki.sock = MagicMock()
    ki.sock.fileno.return_value = 5

    vifi = 1
    ifindex = 10

    ki._add_vif(vifi, ifindex)

    ki.libc.setsockopt.assert_called_once()
    args, _ = ki.libc.setsockopt.call_args
    assert args[0] == 5  # fileno
    assert args[1] == IPPROTO_IP
    assert args[2] == MRT_ADD_VIF

    # Verify the contents of the vifctl struct
    vifctl_ptr = args[3]
    assert isinstance(vifctl_ptr, type(ki.ffi.new("struct vifctl*")))
    assert vifctl_ptr.vifc_vifi == vifi
    assert vifctl_ptr.vifc_flags == VIFF_USE_IFINDEX
    assert vifctl_ptr.vifc_lcl_ifindex == ifindex
    assert args[4] == ki.ffi.sizeof("struct vifctl")


def test_add_mfc_success():
    """
    Tests that _add_mfc correctly populates an mfcctl struct and calls
    setsockopt with MRT_ADD_MFC. This includes the critical endian conversion.
    """
    ki = KernelInterface()
    ki.libc = MagicMock()
    ki.libc.setsockopt.return_value = 0
    ki.sock = MagicMock()
    ki.sock.fileno.return_value = 5

    source_ip = "192.168.1.10"
    group_ip = "239.1.2.3"
    iif_vifi = 0
    oif_vifis = [1, 3]

    ki._add_mfc(source_ip, group_ip, iif_vifi, oif_vifis)

    ki.libc.setsockopt.assert_called_once()
    args, _ = ki.libc.setsockopt.call_args
    assert args[0] == 5
    assert args[1] == IPPROTO_IP
    assert args[2] == MRT_ADD_MFC

    # Verify the contents of the mfcctl struct
    mfcctl_ptr = args[3]
    assert isinstance(mfcctl_ptr, type(ki.ffi.new("struct mfcctl*")))

    # Check IP addresses (verify they were converted to little-endian integers)
    expected_origin = int.from_bytes(socket.inet_aton(source_ip), "little")
    expected_group = int.from_bytes(socket.inet_aton(group_ip), "little")
    assert mfcctl_ptr.mfcc_origin.s_addr == expected_origin
    assert mfcctl_ptr.mfcc_mcastgrp.s_addr == expected_group

    # Check VIF info
    assert mfcctl_ptr.mfcc_parent == iif_vifi
    assert mfcctl_ptr.mfcc_ttls[1] == 1  # TTL threshold is 1 for output VIFs
    assert mfcctl_ptr.mfcc_ttls[3] == 1
    assert mfcctl_ptr.mfcc_ttls[0] == 0  # Input VIF should have TTL 0
    assert mfcctl_ptr.mfcc_ttls[2] == 0  # Unused VIF should have TTL 0

    assert args[4] == ki.ffi.sizeof("struct mfcctl")


def test_del_vif_success():
    """
    Tests that _del_vif correctly populates a vifctl struct and calls
    setsockopt with MRT_DEL_VIF.
    """
    ki = KernelInterface()
    ki.libc = MagicMock()
    ki.libc.setsockopt.return_value = 0
    ki.sock = MagicMock()
    ki.sock.fileno.return_value = 5

    vifi = 1
    ifindex = 10  # Note: ifindex is needed to identify the VIF to delete

    ki._del_vif(vifi, ifindex)

    ki.libc.setsockopt.assert_called_once()
    args, _ = ki.libc.setsockopt.call_args
    assert args[2] == MRT_DEL_VIF

    vifctl_ptr = args[3]
    assert vifctl_ptr.vifc_vifi == vifi
    assert vifctl_ptr.vifc_lcl_ifindex == ifindex


def test_del_mfc_success():
    """
    Tests that _del_mfc correctly populates an mfcctl struct and calls
    setsockopt with MRT_DEL_MFC.
    """
    ki = KernelInterface()
    ki.libc = MagicMock()
    ki.libc.setsockopt.return_value = 0
    ki.sock = MagicMock()
    ki.sock.fileno.return_value = 5

    source_ip = "192.168.1.10"
    group_ip = "239.1.2.3"

    ki._del_mfc(source_ip, group_ip)

    ki.libc.setsockopt.assert_called_once()
    args, _ = ki.libc.setsockopt.call_args
    assert args[2] == MRT_DEL_MFC

    mfcctl_ptr = args[3]
    expected_origin = int.from_bytes(socket.inet_aton(source_ip), "little")
    expected_group = int.from_bytes(socket.inet_aton(group_ip), "little")
    assert mfcctl_ptr.mfcc_origin.s_addr == expected_origin
    assert mfcctl_ptr.mfcc_mcastgrp.s_addr == expected_group
