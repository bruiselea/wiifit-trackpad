from __future__ import annotations

import unittest

from wiifit_trackpad.pointer import TrackpadOptions, TrackpadProcessor
from wiifit_trackpad.reports import BoardState, SensorQuad


def state(x: float | None, y: float | None, buttons: int = 0) -> BoardState:
    sensors = SensorQuad(15, 15, 15, 15) if x is not None else SensorQuad(0, 0, 0, 0)
    return BoardState(sensors, x, y, buttons)


def weighted_state(weight_kg: float, x: float = 0.0, y: float = 0.0) -> BoardState:
    corner = weight_kg / 4.0
    return BoardState(SensorQuad(corner, corner, corner, corner), x, y)


class TrackpadProcessorTests(unittest.TestCase):
    def test_invalid_control_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TrackpadProcessor(TrackpadOptions(control_mode="invalid"))

    def test_first_contact_does_not_move_cursor(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(smoothing=1.0))
        frame = processor.update(state(0.0, 0.0), timestamp=0.0)
        self.assertEqual((frame.delta_x, frame.delta_y), (0, 0))

    def test_moving_foot_right_and_forward_moves_cursor_by_delta(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(gain=2.0, smoothing=0.03))
        processor.update(state(0.0, 0.0), timestamp=0.0)
        frame = processor.update(state(0.5, 0.5), timestamp=0.25)
        self.assertGreater(frame.delta_x, 0)
        self.assertLess(frame.delta_y, 0)

    def test_off_board_does_not_move_pointer(self) -> None:
        processor = TrackpadProcessor()
        self.assertFalse(processor.update(state(None, None), timestamp=0.0).active)

    def test_small_load_above_activation_threshold_moves_pointer(self) -> None:
        processor = TrackpadProcessor(
            TrackpadOptions(smoothing=1.0, activation_weight_kg=0.15)
        )
        tiny_load = BoardState(SensorQuad(0.05, 0.05, 0.05, 0.05), 0.0, 0.0)
        self.assertTrue(processor.update(tiny_load, timestamp=0.0).active)

    def test_sensor_noise_below_activation_threshold_is_ignored(self) -> None:
        processor = TrackpadProcessor(
            TrackpadOptions(smoothing=1.0, activation_weight_kg=0.15)
        )
        noise = BoardState(SensorQuad(0.02, 0.02, 0.02, 0.02), 0.0, 0.0)
        self.assertFalse(processor.update(noise, timestamp=0.0).active)

    def test_sudden_weight_shift_is_smoothed_instead_of_followed_immediately(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(gain=2.0, smoothing=0.30))
        processor.update(state(0.0, 0.0), timestamp=0.0)
        frame = processor.update(state(1.0, 0.0), timestamp=0.01)
        self.assertGreater(frame.delta_x, 0)
        self.assertLess(frame.delta_x, 100)

    def test_tiny_center_of_gravity_jitter_keeps_previous_output(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(gain=2.0, smoothing=0.03))
        first = processor.update(state(0.0, 0.0), timestamp=0.0)
        jitter = processor.update(state(0.001, 0.0), timestamp=0.1)
        self.assertEqual(jitter.delta_x, first.delta_x)

    def test_board_button_clicks_on_rising_edge_only(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(smoothing=1.0))
        self.assertTrue(processor.update(state(0, 0, 1), timestamp=0.0).click)
        self.assertFalse(processor.update(state(0, 0, 1), timestamp=0.1).click)
        self.assertFalse(processor.update(state(0, 0, 0), timestamp=0.2).click)
        self.assertTrue(processor.update(state(0, 0, 1), timestamp=0.3).click)

    def test_quick_weight_increase_clicks_once(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(impact_click_rise_kg=4.0))
        processor.update(weighted_state(30.0), timestamp=0.0)
        processor.update(weighted_state(30.0), timestamp=0.21)
        frame = processor.update(weighted_state(35.0), timestamp=0.26)
        self.assertTrue(frame.click)
        self.assertEqual(frame.click_reason, "load impact")
        self.assertFalse(processor.update(weighted_state(36.0), timestamp=0.27).click)

    def test_slow_weight_increase_does_not_click(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(impact_click_rise_kg=4.0))
        for timestamp, weight in ((0.0, 30), (0.21, 30), (0.31, 31), (0.41, 32), (0.51, 33), (0.61, 34), (0.71, 35)):
            self.assertFalse(processor.update(weighted_state(weight), timestamp=timestamp).click)

    def test_initial_contact_is_not_an_impact_click(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(impact_click_rise_kg=4.0))
        processor.update(state(None, None), timestamp=0.0)
        self.assertFalse(processor.update(weighted_state(60.0), timestamp=0.01).click)

    def test_impact_click_has_cooldown(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(impact_click_rise_kg=4.0))
        processor.update(weighted_state(30.0), timestamp=0.0)
        processor.update(weighted_state(30.0), timestamp=0.21)
        self.assertTrue(processor.update(weighted_state(35.0), timestamp=0.26).click)
        processor.update(weighted_state(30.0), timestamp=0.30)
        self.assertFalse(processor.update(weighted_state(36.0), timestamp=0.35).click)
        processor.update(weighted_state(30.0), timestamp=0.80)
        self.assertTrue(processor.update(weighted_state(36.0), timestamp=0.86).click)

    def test_dwell_click_fires_once_until_pointer_moves(self) -> None:
        options = TrackpadOptions(smoothing=0.03, dwell_click_enabled=True, dwell_seconds=1.0)
        processor = TrackpadProcessor(options)
        self.assertFalse(processor.update(state(0, 0), timestamp=0.0).click)
        self.assertTrue(processor.update(state(0, 0), timestamp=1.0).click)
        self.assertFalse(processor.update(state(0, 0), timestamp=2.0).click)
        self.assertFalse(processor.update(state(0.2, 0), timestamp=2.1).click)
        self.assertTrue(processor.update(state(0.2, 0), timestamp=3.1).click)

    def test_recenter_uses_latest_stance(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(gain=2.0, smoothing=1.0))
        processor.update(state(0.25, -0.25), timestamp=0.0)
        self.assertTrue(processor.recenter())
        frame = processor.update(state(0.25, -0.25), timestamp=0.1)
        self.assertEqual(frame.delta_x, 0)
        self.assertEqual(frame.delta_y, 0)

    def test_lift_and_reposition_does_not_jump_cursor(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(gain=2.0, smoothing=0.03))
        processor.update(state(0.0, 0.0), timestamp=0.0)
        moved = processor.update(state(0.3, 0.0), timestamp=0.25)
        self.assertGreater(moved.delta_x, 0)
        processor.update(state(None, None), timestamp=0.3)
        replaced = processor.update(state(-0.8, 0.4), timestamp=0.4)
        self.assertEqual((replaced.delta_x, replaced.delta_y), (0, 0))

    def test_joystick_lean_moves_continuously_until_returned(self) -> None:
        processor = TrackpadProcessor(
            TrackpadOptions(control_mode="joystick", gain=2.0, smoothing=0.03)
        )
        first = processor.update(state(0.0, 0.0), timestamp=0.0)
        processor.update(state(0.0, 0.0), timestamp=0.40)
        leaning = processor.update(state(0.25, 0.0), timestamp=0.65)
        held = processor.update(state(0.25, 0.0), timestamp=0.90)
        self.assertEqual((first.delta_x, first.delta_y), (0, 0))
        self.assertGreater(leaning.delta_x, 0)
        self.assertGreater(held.delta_x, 0)

    def test_joystick_deadzone_stops_near_neutral(self) -> None:
        processor = TrackpadProcessor(
            TrackpadOptions(control_mode="joystick", gain=2.0, smoothing=0.03)
        )
        processor.update(state(0.0, 0.0), timestamp=0.0)
        processor.update(state(0.0, 0.0), timestamp=0.40)
        frame = processor.update(state(0.004, -0.004), timestamp=0.65)
        self.assertEqual((frame.delta_x, frame.delta_y), (0, 0))

    def test_joystick_small_input_moves_in_all_four_directions(self) -> None:
        cases = (
            ((0.02, 0.0), lambda frame: frame.delta_x > 0),
            ((-0.02, 0.0), lambda frame: frame.delta_x < 0),
            ((0.0, 0.02), lambda frame: frame.delta_y < 0),
            ((0.0, -0.02), lambda frame: frame.delta_y > 0),
        )
        for (x, y), correct_direction in cases:
            with self.subTest(x=x, y=y):
                processor = TrackpadProcessor(
                    TrackpadOptions(control_mode="joystick", gain=2.0, smoothing=0.03)
                )
                processor.update(state(0.0, 0.0), timestamp=0.0)
                processor.update(state(0.0, 0.0), timestamp=0.40)
                frame = processor.update(state(x, y), timestamp=0.65)
                self.assertTrue(correct_direction(frame), frame)

    def test_joystick_ignores_foot_placement_while_finding_neutral(self) -> None:
        processor = TrackpadProcessor(
            TrackpadOptions(control_mode="joystick", gain=2.0, smoothing=0.30)
        )
        first_edge = processor.update(state(-0.8, 0.7), timestamp=0.0)
        placing = processor.update(state(0.3, -0.2), timestamp=0.20)
        settled = processor.update(state(0.1, 0.0), timestamp=0.40)
        neutral = processor.update(state(0.1, 0.0), timestamp=0.50)
        self.assertEqual((first_edge.delta_x, first_edge.delta_y), (0, 0))
        self.assertEqual((placing.delta_x, placing.delta_y), (0, 0))
        self.assertEqual((settled.delta_x, settled.delta_y), (0, 0))
        self.assertEqual((neutral.delta_x, neutral.delta_y), (0, 0))

    def test_switching_to_joystick_mode_does_not_jump(self) -> None:
        processor = TrackpadProcessor(TrackpadOptions(control_mode="trackpad", smoothing=0.03))
        processor.update(state(0.0, 0.0), timestamp=0.0)
        processor.update(state(0.4, 0.0), timestamp=0.25)
        processor.set_options(TrackpadOptions(control_mode="joystick", smoothing=0.03))
        switched = processor.update(state(0.4, 0.0), timestamp=0.30)
        self.assertEqual((switched.delta_x, switched.delta_y), (0, 0))


if __name__ == "__main__":
    unittest.main()
