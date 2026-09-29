"""Pure Wii Balance Board report parsing and calibration math."""

from __future__ import annotations

from dataclasses import dataclass


DATA_REPORT_IDS = (0x32, 0x34)


@dataclass(frozen=True, slots=True)
class SensorQuad:
    top_right: float
    bottom_right: float
    top_left: float
    bottom_left: float

    @property
    def total(self) -> float:
        return self.top_right + self.bottom_right + self.top_left + self.bottom_left


@dataclass(frozen=True, slots=True)
class RawBoardReport:
    sensors: SensorQuad
    buttons: int

    @property
    def board_button_pressed(self) -> bool:
        return self.buttons != 0


@dataclass(frozen=True, slots=True)
class BoardState:
    sensors_kg: SensorQuad
    cog_x: float | None
    cog_y: float | None
    buttons: int = 0

    @property
    def weight_kg(self) -> float:
        return self.sensors_kg.total

    @property
    def on_board(self) -> bool:
        return self.cog_x is not None and self.cog_y is not None

    @property
    def board_button_pressed(self) -> bool:
        return self.buttons != 0


@dataclass(frozen=True, slots=True)
class Calibration:
    kg0: SensorQuad
    kg17: SensorQuad
    kg34: SensorQuad

    @classmethod
    def from_bytes(cls, payload: bytes) -> "Calibration":
        if len(payload) != 24:
            raise ValueError(f"calibration must be exactly 24 bytes, got {len(payload)}")
        calibration = cls(
            kg0=_quad_from_bytes(payload[0:8]),
            kg17=_quad_from_bytes(payload[8:16]),
            kg34=_quad_from_bytes(payload[16:24]),
        )
        for name in ("top_right", "bottom_right", "top_left", "bottom_left"):
            if not (
                getattr(calibration.kg0, name)
                < getattr(calibration.kg17, name)
                < getattr(calibration.kg34, name)
            ):
                raise ValueError(f"non-monotonic calibration data for {name}")
        return calibration

    def calibrate(self, raw: SensorQuad) -> SensorQuad:
        values: dict[str, float] = {}
        for name in ("top_right", "bottom_right", "top_left", "bottom_left"):
            values[name] = _interpolate(
                getattr(raw, name),
                getattr(self.kg0, name),
                getattr(self.kg17, name),
                getattr(self.kg34, name),
            )
        return SensorQuad(**values)

    def state_from_report(self, report: RawBoardReport, min_weight_kg: float = 0.05) -> BoardState:
        sensors = self.calibrate(report.sensors)
        total = sensors.total
        if total < min_weight_kg:
            return BoardState(sensors, None, None, report.buttons)
        right = sensors.top_right + sensors.bottom_right
        left = sensors.top_left + sensors.bottom_left
        front = sensors.top_right + sensors.top_left
        back = sensors.bottom_right + sensors.bottom_left
        return BoardState(
            sensors,
            cog_x=(right - left) / total,
            cog_y=(front - back) / total,
            buttons=report.buttons,
        )


def parse_data_report(report: bytes) -> RawBoardReport:
    """Parse report mode 0x32/0x34 into four raw load-cell values."""

    if report and report[0] == 0 and len(report) > 1 and report[1] in DATA_REPORT_IDS:
        # Some HID backends preserve an extra zero report-id byte.
        report = report[1:]
    if not report:
        raise ValueError("empty HID report")
    report_id = report[0]
    if report_id not in DATA_REPORT_IDS:
        raise ValueError(f"unsupported HID report 0x{report_id:02X}")
    minimum = 11 if report_id == 0x32 else 22
    if len(report) < minimum:
        raise ValueError(f"truncated 0x{report_id:02X} report: {len(report)} < {minimum}")
    extension = report[3:11]
    return RawBoardReport(
        sensors=_quad_from_bytes(extension),
        buttons=int.from_bytes(report[1:3], "little"),
    )


def _quad_from_bytes(payload: bytes) -> SensorQuad:
    if len(payload) != 8:
        raise ValueError("sensor quad must contain 8 bytes")
    values = [int.from_bytes(payload[index : index + 2], "big") for index in range(0, 8, 2)]
    return SensorQuad(
        top_right=values[0],
        bottom_right=values[1],
        top_left=values[2],
        bottom_left=values[3],
    )


def _interpolate(raw: float, kg0: float, kg17: float, kg34: float) -> float:
    if raw <= kg0:
        return 0.0
    if raw < kg17:
        return 17.0 * (raw - kg0) / (kg17 - kg0)
    return 17.0 + 17.0 * (raw - kg17) / (kg34 - kg17)


class ReadTransaction:
    """Reassemble fragmented 0x21 register-read responses."""

    def __init__(self, base_address: int, expected_length: int) -> None:
        if expected_length <= 0:
            raise ValueError("expected_length must be positive")
        self.base_address = base_address
        self.buffer = bytearray(expected_length)
        self._received = [False] * expected_length

    @property
    def complete(self) -> bool:
        return all(self._received)

    @property
    def value(self) -> bytes:
        if not self.complete:
            raise RuntimeError("register read is incomplete")
        return bytes(self.buffer)

    def consume(self, frame: bytes) -> None:
        if frame and frame[0] == 0 and len(frame) > 1 and frame[1] == 0x21:
            frame = frame[1:]
        if len(frame) < 22 or frame[0] != 0x21:
            raise ValueError("not a complete 0x21 register-read response")
        size_and_error = frame[3]
        # Wiimote 0x21: high nibble is payload size minus one; low nibble is error.
        size = (size_and_error >> 4) + 1
        error = size_and_error & 0x0F
        if error:
            raise OSError(f"board register-read error 0x{error:X}")
        address_low = int.from_bytes(frame[4:6], "big")
        offset = (address_low - (self.base_address & 0xFFFF)) & 0xFFFF
        if offset + size > len(self.buffer):
            raise ValueError("register-read response exceeds requested range")
        self.buffer[offset : offset + size] = frame[6 : 6 + size]
        self._received[offset : offset + size] = [True] * size
