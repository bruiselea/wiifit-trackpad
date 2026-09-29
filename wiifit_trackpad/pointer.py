"""Pure trackpad mapping plus the Win32 SendInput pointer backend."""

from __future__ import annotations

import ctypes
import math
from collections import deque
from dataclasses import dataclass
from time import monotonic

from .reports import BoardState


@dataclass(slots=True)
class TrackpadOptions:
    control_mode: str = "trackpad"
    gain: float = 2.4
    # Low-pass time constant in seconds. Higher values move more smoothly.
    smoothing: float = 0.30
    activation_weight_kg: float = 0.15
    invert_x: bool = False
    invert_y: bool = False
    impact_click_enabled: bool = True
    impact_click_rise_kg: float = 4.0
    dwell_click_enabled: bool = False
    dwell_seconds: float = 1.0
    dwell_radius: float = 0.018

    def validate(self) -> None:
        if self.control_mode not in {"trackpad", "joystick"}:
            raise ValueError("control_mode must be 'trackpad' or 'joystick'")
        if not 0.25 <= self.gain <= 8.0:
            raise ValueError("gain must be between 0.25 and 8.0")
        if not 0.0 < self.smoothing <= 1.0:
            raise ValueError("smoothing must be within (0, 1]")
        if not 0.05 <= self.activation_weight_kg <= 10.0:
            raise ValueError("activation_weight_kg must be between 0.05 and 10.0")
        if not 1.0 <= self.impact_click_rise_kg <= 20.0:
            raise ValueError("impact_click_rise_kg must be between 1.0 and 20.0")
        if not 0.3 <= self.dwell_seconds <= 5.0:
            raise ValueError("dwell_seconds must be between 0.3 and 5.0")
        if not 0.001 <= self.dwell_radius <= 0.2:
            raise ValueError("dwell_radius must be between 0.001 and 0.2")


@dataclass(frozen=True, slots=True)
class PointerFrame:
    active: bool
    delta_x: int = 0
    delta_y: int = 0
    click: bool = False
    click_reason: str = ""


class TrackpadProcessor:
    """Map center-of-pressure movement to relative cursor movement."""

    def __init__(self, options: TrackpadOptions | None = None) -> None:
        self.options = options or TrackpadOptions()
        self.options.validate()
        self._filtered_x: float | None = None
        self._filtered_y: float | None = None
        self._last_filter_time: float | None = None
        self._motion_anchor_x: float | None = None
        self._motion_anchor_y: float | None = None
        self._joystick_remainder_x = 0.0
        self._joystick_remainder_y = 0.0
        self._joystick_settling_until = -math.inf
        self._button_was_pressed = False
        self._impact_samples: deque[tuple[float, float]] = deque()
        self._impact_armed_at = math.inf
        self._last_impact_click = -math.inf
        self._dwell_anchor: tuple[float, float] | None = None
        self._dwell_started = 0.0
        self._dwell_fired = False
        self._latest_state: BoardState | None = None

    def set_options(self, options: TrackpadOptions) -> None:
        options.validate()
        mode_changed = options.control_mode != self.options.control_mode
        self.options = options
        if mode_changed:
            # Switching modes starts from the current foot position on the next
            # report, preventing a cursor jump between two different mappings.
            self._filtered_x = None
            self._filtered_y = None
            self._last_filter_time = None
            self._motion_anchor_x = None
            self._motion_anchor_y = None
            self._joystick_remainder_x = 0.0
            self._joystick_remainder_y = 0.0
            self._joystick_settling_until = -math.inf
            self._reset_dwell()

    def recenter(self) -> bool:
        state = self._latest_state
        if state is None or not state.on_board:
            return False
        self._filtered_x = float(state.cog_x)
        self._filtered_y = float(state.cog_y)
        self._last_filter_time = None
        self._motion_anchor_x = self._filtered_x
        self._motion_anchor_y = self._filtered_y
        self._joystick_remainder_x = 0.0
        self._joystick_remainder_y = 0.0
        self._joystick_settling_until = -math.inf
        self._reset_dwell()
        return True

    def update(self, state: BoardState, timestamp: float | None = None) -> PointerFrame:
        now = monotonic() if timestamp is None else timestamp
        self._latest_state = state
        if not state.on_board or state.weight_kg < self.options.activation_weight_kg:
            self._filtered_x = None
            self._filtered_y = None
            self._last_filter_time = None
            self._motion_anchor_x = None
            self._motion_anchor_y = None
            self._joystick_remainder_x = 0.0
            self._joystick_remainder_y = 0.0
            self._joystick_settling_until = -math.inf
            self._button_was_pressed = state.board_button_pressed
            self._reset_impact()
            self._reset_dwell()
            return PointerFrame(active=False)

        raw_x = float(state.cog_x)
        raw_y = float(state.cog_y)
        elapsed = 0.0
        if self._filtered_x is None or self._filtered_y is None:
            self._filtered_x = raw_x
            self._filtered_y = raw_y
            self._motion_anchor_x = raw_x
            self._motion_anchor_y = raw_y
            if self.options.control_mode == "joystick":
                self._joystick_settling_until = now + 0.45
            self._impact_samples.clear()
            self._impact_samples.append((now, state.weight_kg))
            # Getting onto the board is contact, not a click. Give the load a
            # moment to settle before accepting a deliberate tap.
            self._impact_armed_at = now + 0.20
        elif self.options.control_mode == "joystick" and now < self._joystick_settling_until:
            # The first few load reports usually come from just a toe or one edge
            # while the foot is being placed. Follow that settling stance directly
            # instead of freezing the first noisy point as joystick neutral.
            self._filtered_x = raw_x
            self._filtered_y = raw_y
            self._motion_anchor_x = raw_x
            self._motion_anchor_y = raw_y
            self._joystick_remainder_x = 0.0
            self._joystick_remainder_y = 0.0
        else:
            previous_time = self._last_filter_time
            elapsed = 0.01 if previous_time is None else max(0.001, min(now - previous_time, 0.25))
            # Time-based exponential smoothing behaves consistently at different HID report rates.
            alpha = 1.0 - math.exp(-elapsed / self.options.smoothing)
            self._filtered_x += alpha * (raw_x - self._filtered_x)
            self._filtered_y += alpha * (raw_y - self._filtered_y)
        self._last_filter_time = now

        anchor_x = self._motion_anchor_x if self._motion_anchor_x is not None else self._filtered_x
        anchor_y = self._motion_anchor_y if self._motion_anchor_y is not None else self._filtered_y
        movement_x = self._filtered_x - anchor_x
        movement_y = self._filtered_y - anchor_y

        if self.options.control_mode == "joystick" and now < self._joystick_settling_until:
            delta_x, delta_y = 0, 0
        elif self.options.control_mode == "joystick":
            delta_x, delta_y = self._joystick_movement(movement_x, movement_y, elapsed)
        else:
            delta_x, delta_y = self._trackpad_movement(movement_x, movement_y)

        board_click = state.board_button_pressed and not self._button_was_pressed
        self._button_was_pressed = state.board_button_pressed
        impact_click = self._update_impact_click(state.weight_kg, now)
        dwell_click = self._update_dwell(self._filtered_x, self._filtered_y, now)
        reason = (
            "board button"
            if board_click
            else "load impact"
            if impact_click
            else "dwell"
            if dwell_click
            else ""
        )
        return PointerFrame(
            active=True,
            delta_x=delta_x,
            delta_y=delta_y,
            click=board_click or impact_click or dwell_click,
            click_reason=reason,
        )

    def _trackpad_movement(self, movement_x: float, movement_y: float) -> tuple[int, int]:
        # Slow intentional motion accumulates across reports; ordinary sensor tremor
        # remains inside this threshold and never reaches the cursor.
        cog_deadband = 0.003
        pixels_per_cog_unit = 600.0 * self.options.gain
        delta_x = 0
        delta_y = 0
        if abs(movement_x) >= cog_deadband:
            sign = -1 if self.options.invert_x else 1
            delta_x = round(movement_x * pixels_per_cog_unit * sign)
            self._motion_anchor_x = self._filtered_x
        if abs(movement_y) >= cog_deadband:
            # Forward is positive on the board but upward is negative on screen.
            sign = 1 if self.options.invert_y else -1
            delta_y = round(movement_y * pixels_per_cog_unit * sign)
            self._motion_anchor_y = self._filtered_y
        return delta_x, delta_y

    def _joystick_movement(
        self, movement_x: float, movement_y: float, elapsed: float
    ) -> tuple[int, int]:
        # In joystick mode the anchor remains fixed as a neutral point. Holding a
        # lean therefore emits motion continuously, with a quiet area near neutral.
        x_power = _joystick_power(movement_x)
        y_power = _joystick_power(movement_y)
        max_speed_px_s = 750.0 * self.options.gain
        x_sign = -1 if self.options.invert_x else 1
        y_sign = 1 if self.options.invert_y else -1

        x_distance = x_power * max_speed_px_s * elapsed * x_sign + self._joystick_remainder_x
        y_distance = y_power * max_speed_px_s * elapsed * y_sign + self._joystick_remainder_y
        delta_x = math.trunc(x_distance)
        delta_y = math.trunc(y_distance)
        self._joystick_remainder_x = x_distance - delta_x if x_power else 0.0
        self._joystick_remainder_y = y_distance - delta_y if y_power else 0.0
        return delta_x, delta_y

    def _update_impact_click(self, weight_kg: float, now: float) -> bool:
        if not self.options.impact_click_enabled:
            self._impact_samples.clear()
            self._impact_samples.append((now, weight_kg))
            return False

        window_seconds = 0.18
        cooldown_seconds = 0.45
        while self._impact_samples and now - self._impact_samples[0][0] > window_seconds:
            self._impact_samples.popleft()

        clicked = False
        if self._impact_samples and now >= self._impact_armed_at:
            baseline_time, baseline_weight = min(self._impact_samples, key=lambda sample: sample[1])
            rise = weight_kg - baseline_weight
            elapsed = max(now - baseline_time, 0.001)
            rise_rate = rise / elapsed
            minimum_rate = self.options.impact_click_rise_kg / window_seconds
            if (
                rise >= self.options.impact_click_rise_kg
                and rise_rate >= minimum_rate
                and now - self._last_impact_click >= cooldown_seconds
            ):
                clicked = True
                self._last_impact_click = now
                # The peak becomes the new baseline so one impact cannot emit
                # multiple clicks across adjacent HID reports.
                self._impact_samples.clear()

        self._impact_samples.append((now, weight_kg))
        return clicked

    def _reset_impact(self) -> None:
        self._impact_samples.clear()
        self._impact_armed_at = math.inf

    def _update_dwell(self, x: float, y: float, now: float) -> bool:
        if not self.options.dwell_click_enabled:
            self._reset_dwell()
            return False
        if self._dwell_anchor is None:
            self._dwell_anchor = (x, y)
            self._dwell_started = now
            return False
        distance = ((x - self._dwell_anchor[0]) ** 2 + (y - self._dwell_anchor[1]) ** 2) ** 0.5
        if distance > self.options.dwell_radius:
            self._dwell_anchor = (x, y)
            self._dwell_started = now
            self._dwell_fired = False
            return False
        if not self._dwell_fired and now - self._dwell_started >= self.options.dwell_seconds:
            self._dwell_fired = True
            return True
        return False

    def _reset_dwell(self) -> None:
        self._dwell_anchor = None
        self._dwell_started = 0.0
        self._dwell_fired = False


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _joystick_power(displacement: float) -> float:
    # A resting foot often has much less travel toward the nearest board edge.
    # Keep this close to the trackpad noise floor so all four directions remain
    # usable even from an off-center stance; smoothing handles the residual noise.
    deadzone = 0.008
    full_speed_at = 0.22
    magnitude = abs(displacement)
    if magnitude <= deadzone:
        return 0.0
    normalized = min(1.0, (magnitude - deadzone) / (full_speed_at - deadzone))
    curved = normalized**1.35
    return math.copysign(curved, displacement)


class WindowsPointer:
    """Inject pointer movement with Win32 SendInput."""

    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_VIRTUALDESK = 0x4000
    MOUSEEVENTF_ABSOLUTE = 0x8000

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class InputUnion(ctypes.Union):
        pass

    class Input(ctypes.Structure):
        pass

    InputUnion._fields_ = [("mi", MouseInput)]
    Input._anonymous_ = ("union",)
    Input._fields_ = [("type", ctypes.c_ulong), ("union", InputUnion)]

    def move_absolute(self, x: float, y: float) -> None:
        flags = self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE | self.MOUSEEVENTF_VIRTUALDESK
        self._send(round(_clamp01(x) * 65535), round(_clamp01(y) * 65535), flags)

    def move_relative(self, delta_x: int, delta_y: int) -> None:
        if delta_x == 0 and delta_y == 0:
            return
        self._send(delta_x, delta_y, self.MOUSEEVENTF_MOVE)

    def click_left(self) -> None:
        self._send(0, 0, self.MOUSEEVENTF_LEFTDOWN)
        self._send(0, 0, self.MOUSEEVENTF_LEFTUP)

    def _send(self, x: int, y: int, flags: int) -> None:
        item = self.Input(
            type=self.INPUT_MOUSE,
            union=self.InputUnion(mi=self.MouseInput(dx=x, dy=y, dwFlags=flags)),
        )
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item))
        if sent != 1:
            raise ctypes.WinError()
