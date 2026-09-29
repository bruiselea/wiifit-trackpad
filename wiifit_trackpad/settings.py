"""Small per-user settings document."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .pointer import TrackpadOptions


@dataclass(slots=True)
class AppSettings:
    control_mode: str = "trackpad"
    gain: float = 2.4
    smoothing: float = 0.30
    activation_weight_kg: float = 0.15
    invert_x: bool = False
    invert_y: bool = False
    impact_click_enabled: bool = True
    impact_click_rise_kg: float = 4.0
    dwell_click_enabled: bool = False
    dwell_seconds: float = 1.0

    def to_trackpad_options(self) -> TrackpadOptions:
        options = TrackpadOptions(
            control_mode=self.control_mode,
            gain=self.gain,
            smoothing=self.smoothing,
            activation_weight_kg=self.activation_weight_kg,
            invert_x=self.invert_x,
            invert_y=self.invert_y,
            impact_click_enabled=self.impact_click_enabled,
            impact_click_rise_kg=self.impact_click_rise_kg,
            dwell_click_enabled=self.dwell_click_enabled,
            dwell_seconds=self.dwell_seconds,
        )
        options.validate()
        return options

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            settings = cls(
                control_mode=str(payload.get("control_mode", "trackpad")),
                gain=float(payload.get("gain", 2.4)),
                smoothing=float(payload.get("smoothing", 0.30)),
                activation_weight_kg=float(payload.get("activation_weight_kg", 0.15)),
                invert_x=bool(payload.get("invert_x", False)),
                invert_y=bool(payload.get("invert_y", False)),
                impact_click_enabled=bool(payload.get("impact_click_enabled", True)),
                impact_click_rise_kg=float(payload.get("impact_click_rise_kg", 4.0)),
                dwell_click_enabled=bool(payload.get("dwell_click_enabled", False)),
                dwell_seconds=float(payload.get("dwell_seconds", 1.0)),
            )
            settings.to_trackpad_options()
            return settings
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self, path: Path) -> None:
        self.to_trackpad_options()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, **asdict(self)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
