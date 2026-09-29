from __future__ import annotations

import unittest

from wiifit_trackpad.reports import (
    Calibration,
    ReadTransaction,
    SensorQuad,
    parse_data_report,
)


class ReportTests(unittest.TestCase):
    def test_parse_032_report(self) -> None:
        report = bytes((0x32, 0x00, 0x08, 0x10, 0x00, 0x20, 0x00, 0x30, 0x00, 0x40, 0x00))
        parsed = parse_data_report(report)
        self.assertEqual(parsed.sensors.top_right, 0x1000)
        self.assertEqual(parsed.sensors.bottom_left, 0x4000)
        self.assertTrue(parsed.board_button_pressed)

    def test_parse_accepts_leading_zero_report_id(self) -> None:
        report = bytes((0, 0x32, 0, 0, 0x10, 0, 0x20, 0, 0x30, 0, 0x40, 0))
        self.assertEqual(parse_data_report(report).sensors.top_left, 0x3000)

    def test_calibration_and_center_of_gravity(self) -> None:
        values = []
        for point in (5000, 10000, 15000):
            values.extend(point.to_bytes(2, "big") * 4)
        calibration = Calibration.from_bytes(bytes(values))
        report = parse_data_report(
            bytes((0x32, 0, 0))
            + b"".join(value.to_bytes(2, "big") for value in (10000, 10000, 5000, 5000))
        )
        state = calibration.state_from_report(report)
        self.assertAlmostEqual(state.weight_kg, 34.0)
        self.assertAlmostEqual(state.cog_x, 1.0)
        self.assertAlmostEqual(state.cog_y, 0.0)

    def test_calibration_rejects_non_monotonic_data(self) -> None:
        with self.assertRaises(ValueError):
            Calibration.from_bytes(bytes(24))

    def test_read_transaction_reassembles_fragments(self) -> None:
        tx = ReadTransaction(0x00A40024, 24)
        tx.consume(_read_frame(0x0034, bytes((2,)) * 8))
        tx.consume(_read_frame(0x0024, bytes((1,)) * 16))
        self.assertTrue(tx.complete)
        self.assertEqual(tx.value, bytes((1,)) * 16 + bytes((2,)) * 8)

    def test_read_transaction_reads_error_from_low_nibble(self) -> None:
        tx = ReadTransaction(0x00A40024, 1)
        frame = bytearray(_read_frame(0x0024, b"\x00"))
        frame[3] |= 0x07
        with self.assertRaisesRegex(OSError, "0x7"):
            tx.consume(bytes(frame))


def _read_frame(address_low: int, payload: bytes) -> bytes:
    frame = bytearray(22)
    frame[0] = 0x21
    frame[3] = (len(payload) - 1) << 4
    frame[4:6] = address_low.to_bytes(2, "big")
    frame[6 : 6 + len(payload)] = payload
    return bytes(frame)


if __name__ == "__main__":
    unittest.main()
