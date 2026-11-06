"""Exercise the ctypes boundary using a compiled C test double."""

import pytest

from dune_dscs.devices.fers import A5202, FersError, HvStatus


@pytest.mark.parametrize("path", ["eth:192.0.2.1", "usb:12345"])
def test_identity_and_connection_lifetime(sdk, path):
    library, control = sdk
    board = A5202(path, library=library)
    assert control.stub_opened() == 0
    with board:
        board.open()  # Opening the same object twice must not leak a handle.
        assert control.stub_opened() == 1
        assert board.library_version == "2.2.2"
        info = board.board_info()
        assert (info.pid, info.fers_code, info.channels) == (12345, 5202, 64)
        assert (info.pcb_revision, info.form_factor) == (3, 0)
        assert (info.model_name, info.model_code) == ("A5202", "WA5202XAAAAA")
        assert (info.fpga_firmware, info.mcu_firmware) == (0xFEDCBA98, 0x87654321)
    board.close()
    assert control.stub_opened() == 0
    assert control.stub_closes() == 1
    with pytest.raises(RuntimeError, match="closed"):
        board.read("voltage_v")
    with board:
        assert control.stub_opened() == 1


def test_registers_keep_all_32_bits(sdk):
    library, _ = sdk
    with A5202("eth:192.0.2.1", library=library) as board:
        board.write_register(0xFFFFFFFF, 0xFEDCBA98)
        assert board.read_register(0xFFFFFFFF) == 0xFEDCBA98
        for invalid in (-1, 0x100000000, 1.5, True, "1"):
            with pytest.raises(ValueError, match="32-bit"):
                board.read_register(invalid)
            with pytest.raises(ValueError, match="32-bit"):
                board.write_register(0xFFFFFFFF, invalid)


def test_live_readings_and_explicit_hv_writes(sdk):
    library, _ = sdk
    with A5202("eth:192.0.2.1", library=library) as board:
        assert board.hv_status() == HvStatus(False, True, False, True)
        assert board.read("board_temperature_c") == 24.5
        assert board.read("fpga_temperature_c") == 42.25
        assert board.read("hv_temperature_c") == 30
        assert board.read("detector_temperature_c") == 21.75
        assert board.read("current_ma") == pytest.approx(0.1234)
        assert board.read("bias_voltage_v") == 55
        board.set_bias_voltage(56.125)
        assert board.read("bias_voltage_v") == 56.125
        assert board.read("voltage_v") == pytest.approx(56.025)
        board.set_current_limit(0.75)
        assert board.read("current_limit_ma") == 0.75
        board.set_hv_enabled(True)
        assert board.hv_status().enabled is True
    # Closing does not switch off the output or change the setpoint.
    with board:
        assert board.hv_status().enabled is True
        assert board.read("bias_voltage_v") == 56.125
        board.set_hv_enabled(False)
        assert board.hv_status().enabled is False


@pytest.mark.parametrize("value", [999, float("nan"), float("inf")])
def test_invalid_temperature_is_an_error(sdk, value):
    library, control = sdk
    with A5202("eth:192.0.2.1", library=library) as board:
        control.stub_temperature(value)
        with pytest.raises(FersError, match="Invalid sensor reading"):
            board.read("board_temperature_c")


def test_sdk_failure_has_operation_code_and_message(sdk):
    library, control = sdk
    with A5202("eth:192.0.2.1", library=library) as board:
        control.stub_fail(-2)
        with pytest.raises(FersError, match="simulated communication failure") as error:
            board.read("voltage_v")
        assert error.value.code == -2
        assert error.value.operation == "FERS_HV_Get_Vmon"
        assert board.read("voltage_v") == pytest.approx(54.9)
        control.stub_fail(-2)
        with pytest.raises(FersError):
            board.set_hv_enabled(True)
        assert board.hv_status().enabled is False


def test_failed_open_can_be_retried(sdk):
    library, control = sdk
    board = A5202("eth:192.0.2.1", library=library)
    control.stub_fail(-2)
    with pytest.raises(FersError):
        board.open()
    board.close()
    assert control.stub_closes() == 0
    with board:
        assert control.stub_opened() == 1


def test_failed_close_keeps_handle_for_retry(sdk):
    library, control = sdk
    board = A5202("eth:192.0.2.1", library=library).open()
    control.stub_fail(-2)
    with pytest.raises(FersError):
        board.close()
    assert control.stub_opened() == 1
    board.close()
    assert control.stub_opened() == 0


def test_wrong_board_is_closed(sdk):
    library, control = sdk
    control.stub_model(5203)
    with pytest.raises(ValueError, match="Expected a 5202"):
        A5202("eth:192.0.2.1", library=library).open()
    assert control.stub_opened() == 0


def test_context_closes_on_application_error(sdk):
    library, control = sdk
    with (
        pytest.raises(ValueError, match="application failed"),
        A5202("eth:192.0.2.1", library=library),
    ):
        raise ValueError("application failed")
    assert control.stub_opened() == 0


def test_hv_arguments_are_checked_before_native_calls(sdk):
    library, _ = sdk
    with A5202("eth:192.0.2.1", library=library) as board:
        for value in (19.9, 85.1, float("nan"), float("inf"), True, "55"):
            with pytest.raises((TypeError, ValueError)):
                board.set_bias_voltage(value)
        for value in (-0.1, 10.1, float("nan"), True, "1"):
            with pytest.raises((TypeError, ValueError)):
                board.set_current_limit(value)
        for value in (0, 1, "false", None):
            with pytest.raises(ValueError):
                board.set_hv_enabled(value)
        with pytest.raises(ValueError, match="Unknown quantity"):
            board.read("unavailable")
        assert board.read("bias_voltage_v") == 55
        assert board.read("current_limit_ma") == 1


@pytest.mark.parametrize("path", [
    "", None, "192.0.2.1", "eth:999.0.0.1", "eth:192.0.2.1\x00",
    "eth:192.0.2.1:tdl:0:0", "usb:-1", "usb:2147483648", "usb:",
    "usb:123456789012345678901234567890", "usb:１２３", "offline:0",
])
def test_bad_paths_fail_without_loading_a_library(path):
    with pytest.raises((TypeError, ValueError)):
        A5202(path, library="/does/not/exist")


def test_library_is_optional_until_open(monkeypatch):
    monkeypatch.delenv("CAEN_FERSLIB_LIBRARY", raising=False)
    board = A5202("eth:192.0.2.1", library="/does/not/exist")
    board.close()
    with pytest.raises(OSError):
        board.open()


def test_library_can_be_selected_by_environment(sdk, monkeypatch):
    library, _ = sdk
    monkeypatch.setenv("CAEN_FERSLIB_LIBRARY", str(library))
    with A5202("eth:192.0.2.1") as board:
        assert board.library_version == "2.2.2"
