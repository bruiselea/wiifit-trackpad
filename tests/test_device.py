from __future__ import annotations

import unittest

from wiifit_trackpad.device import DeviceInfo, select_balance_board


def device(product: str) -> DeviceInfo:
    return DeviceInfo(b"path", 0x057E, 0x0306, "Nintendo", product, "")


class DeviceSelectionTests(unittest.TestCase):
    def test_named_board_is_preferred(self) -> None:
        selected = select_balance_board(
            [device("Nintendo RVL-CNT-01"), device("Nintendo RVL-WBC-01")]
        )
        self.assertEqual(selected.product, "Nintendo RVL-WBC-01")

    def test_rvl_cnt_name_is_probed_because_windows_can_mask_board_name(self) -> None:
        selected = select_balance_board([device("Nintendo RVL-CNT-01")])
        self.assertEqual(selected.product, "Nintendo RVL-CNT-01")

    def test_generic_windows_hid_can_be_fallback(self) -> None:
        selected = select_balance_board([device("HID-compliant game controller")])
        self.assertEqual(selected.product, "HID-compliant game controller")


if __name__ == "__main__":
    unittest.main()
