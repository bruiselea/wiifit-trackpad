"""Discover and stream a paired Wii Fit Balance Board through hidapi."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic, sleep
from typing import Iterator

import hid

from .reports import BoardState, Calibration, ReadTransaction, parse_data_report


NINTENDO_VENDOR_ID = 0x057E
WIIMOTE_PRODUCT_ID = 0x0306
BALANCE_BOARD_PRODUCT_MARKER = "RVL-WBC-01"
CALIBRATION_ADDRESS = 0x00A40024


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    path: bytes
    vendor_id: int
    product_id: int
    manufacturer: str
    product: str
    serial_number: str

    @property
    def identifier(self) -> str:
        return f"{self.vendor_id:04X}:{self.product_id:04X}"

    @property
    def is_named_balance_board(self) -> bool:
        return BALANCE_BOARD_PRODUCT_MARKER in self.product.upper()


def enumerate_devices() -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for raw in hid.enumerate(NINTENDO_VENDOR_ID, WIIMOTE_PRODUCT_ID):
        path = raw.get("path")
        if not path:
            continue
        devices.append(
            DeviceInfo(
                path=path,
                vendor_id=raw["vendor_id"],
                product_id=raw["product_id"],
                manufacturer=raw.get("manufacturer_string") or "Nintendo",
                product=raw.get("product_string") or "Nintendo HID device",
                serial_number=raw.get("serial_number") or "",
            )
        )
    return sorted(devices, key=lambda item: not item.is_named_balance_board)


def select_balance_board(devices: list[DeviceInfo] | None = None) -> DeviceInfo:
    """Prefer a named board, then probe other Nintendo 057E:0306 candidates.

    Windows Bluetooth drivers can expose a real Balance Board with the generic
    ``RVL-CNT-01`` product string. The shared VID/PID and product name therefore
    cannot identify the extension reliably; ``BalanceBoardDevice.initialize``
    performs the authoritative check by reading the board's calibration block.
    """

    candidates = enumerate_devices() if devices is None else devices
    named = [item for item in candidates if item.is_named_balance_board]
    if named:
        return named[0]
    if candidates:
        return candidates[0]
    raise OSError(
        "Nintendo RVL-WBC-01 が見つかりません。Bluetoothでペアリングし、"
        "電池カバー内のSYNCを押してください。"
    )


class BalanceBoardDevice:
    def __init__(self, info: DeviceInfo, poll_interval: float = 0.005) -> None:
        self.info = info
        self.poll_interval = poll_interval
        self._device: hid.device | None = None
        self.calibration: Calibration | None = None

    def __enter__(self) -> "BalanceBoardDevice":
        device = hid.device()
        device.open_path(self.info.path)
        device.set_nonblocking(True)
        self._device = device
        return self

    def __exit__(self, *_: object) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None

    def initialize(self) -> Calibration:
        self._write_register(0x00A400F0, b"\x55")
        try:
            self._write_register(0x00A400FB, b"\x00")
        except OSError:
            # Some board firmware completes initialization despite rejecting this acknowledgement.
            pass
        payload = self._read_register(CALIBRATION_ADDRESS, 24)
        self.calibration = Calibration.from_bytes(payload)
        self._write(bytes((0x12, 0x04, 0x32)))
        return self.calibration

    def states(
        self,
        *,
        deadline: float | None = None,
        stop_event: Event | None = None,
        min_weight_kg: float = 0.05,
    ) -> Iterator[BoardState]:
        if self._device is None:
            raise RuntimeError("device is not open")
        if self.calibration is None:
            raise RuntimeError("device is not initialized")
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            if deadline is not None and monotonic() >= deadline:
                return
            report = bytes(self._device.read(64))
            if not report:
                sleep(self.poll_interval)
                continue
            try:
                parsed = parse_data_report(report)
            except ValueError:
                continue
            yield self.calibration.state_from_report(parsed, min_weight_kg)

    def _write(self, payload: bytes) -> None:
        if self._device is None:
            raise RuntimeError("device is not open")
        written = self._device.write(payload)
        if written <= 0:
            raise OSError("could not write to Wii Balance Board HID")

    def _write_register(self, address: int, data: bytes) -> None:
        if not 1 <= len(data) <= 16:
            raise ValueError("register writes must contain 1..16 bytes")
        payload = bytearray(22)
        payload[0] = 0x16
        payload[1] = 0x04
        payload[2:5] = address.to_bytes(4, "big")[1:]
        payload[5] = len(data)
        payload[6 : 6 + len(data)] = data
        self._write(bytes(payload))

    def _read_register(self, address: int, length: int, timeout: float = 2.0) -> bytes:
        if self._device is None:
            raise RuntimeError("device is not open")
        payload = bytearray(7)
        payload[0] = 0x17
        payload[1] = 0x04
        payload[2:5] = address.to_bytes(4, "big")[1:]
        payload[5:7] = length.to_bytes(2, "big")
        self._write(bytes(payload))

        transaction = ReadTransaction(address, length)
        deadline = monotonic() + timeout
        while not transaction.complete:
            if monotonic() >= deadline:
                raise TimeoutError("board did not return calibration data within 2 seconds")
            frame = bytes(self._device.read(64))
            if not frame:
                sleep(self.poll_interval)
                continue
            report_id = frame[1] if frame[0] == 0 and len(frame) > 1 else frame[0]
            if report_id == 0x21:
                transaction.consume(frame)
        return transaction.value
