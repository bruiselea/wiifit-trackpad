"""Tkinter dashboard modeled after the user's SpaceMouse bridge app."""

from __future__ import annotations

import os
import queue
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from .controller import (
    STATE_ACTIVE,
    STATE_CONNECTING,
    STATE_ERROR,
    ControllerSnapshot,
    TrackpadController,
)
from .logging_setup import configure_logging
from .paths import user_log_path, user_settings_path
from .settings import AppSettings
from .version import PRODUCT_NAME, PRODUCT_VERSION


class TrackpadDashboard:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(PRODUCT_NAME)
        self.root.geometry("680x780")
        self.root.minsize(620, 710)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.settings_path = user_settings_path()
        self.settings = AppSettings.load(self.settings_path)
        self.log_path = user_log_path()
        self.logger = configure_logging(self.log_path)
        self.snapshot_queue: queue.Queue[ControllerSnapshot] = queue.Queue(maxsize=64)
        self.controller = TrackpadController(
            self.settings.to_trackpad_options(),
            on_snapshot=self._enqueue_snapshot,
            logger=self.logger,
        )

        self.status_var = tk.StringVar(value="停止中")
        self.detail_var = tk.StringVar(value="「開始」を押してWii Fitボードへ接続します。")
        self.device_var = tk.StringVar(value="未接続")
        self.weight_var = tk.StringVar(value="— kg")
        self.cog_var = tk.StringVar(value="X — / Y —")
        self.control_mode_var = tk.StringVar(value=self.settings.control_mode)
        self.gain_var = tk.DoubleVar(value=self.settings.gain)
        self.smoothing_var = tk.DoubleVar(value=self.settings.smoothing)
        self.activation_weight_var = tk.DoubleVar(value=self.settings.activation_weight_kg)
        self.invert_x_var = tk.BooleanVar(value=self.settings.invert_x)
        self.invert_y_var = tk.BooleanVar(value=self.settings.invert_y)
        self.impact_click_enabled_var = tk.BooleanVar(value=self.settings.impact_click_enabled)
        self.impact_click_rise_var = tk.DoubleVar(value=self.settings.impact_click_rise_kg)
        self.dwell_enabled_var = tk.BooleanVar(value=self.settings.dwell_click_enabled)
        self.dwell_seconds_var = tk.DoubleVar(value=self.settings.dwell_seconds)

        self._build_ui()
        self.root.after(75, self._drain_snapshots)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Good.TLabel", foreground="#16803a", font=("Segoe UI", 15, "bold"))
        style.configure("Error.TLabel", foreground="#b3261e", font=("Segoe UI", 15, "bold"))

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text=PRODUCT_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=PRODUCT_VERSION, foreground="#68727d").pack(
            side="left", padx=(10, 0), pady=(8, 0)
        )

        status = ttk.LabelFrame(outer, text="現在の状態", padding=14)
        status.pack(fill="x", pady=(18, 12))
        self.status_label = ttk.Label(status, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(anchor="w")
        ttk.Label(status, textvariable=self.detail_var, wraplength=590, foreground="#59636e").pack(
            anchor="w", pady=(5, 0)
        )

        # Keep the primary controls directly below status. On high-DPI or short
        # displays, controls placed at the bottom can be pushed below the visible area.
        buttons = ttk.LabelFrame(outer, text="操作", padding=10)
        buttons.pack(fill="x", pady=(0, 12))
        self.start_button = ttk.Button(buttons, text="▶ 開始", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="■ 停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(7, 0))
        ttk.Button(buttons, text="基準位置をリセット", command=self.recenter).pack(
            side="left", padx=(7, 0)
        )
        ttk.Button(buttons, text="ログを開く", command=self.open_logs).pack(side="left", padx=(7, 0))
        ttk.Button(buttons, text="終了", command=self.close).pack(side="right")

        live = ttk.LabelFrame(outer, text="ライブ入力", padding=12)
        live.pack(fill="x")
        for row, (label, variable) in enumerate(
            (("デバイス", self.device_var), ("総荷重", self.weight_var), ("重心", self.cog_var))
        ):
            ttk.Label(live, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Label(live, textvariable=variable).grid(row=row, column=1, sticky="e", pady=3)
        live.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(live, height=185, background="#eef2f6", highlightthickness=0)
        self.canvas.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.canvas.bind("<Configure>", lambda _event: self._draw_board(None, None))
        self._dot: int | None = None

        settings = ttk.LabelFrame(outer, text="カーソル操作設定", padding=12)
        settings.pack(fill="x", pady=(12, 0))
        ttk.Label(settings, text="操作モード").grid(row=0, column=0, sticky="w")
        mode_choices = ttk.Frame(settings)
        mode_choices.grid(row=0, column=1, columnspan=2, sticky="w", padx=(10, 0))
        ttk.Radiobutton(
            mode_choices,
            text="相対トラックパッド",
            value="trackpad",
            variable=self.control_mode_var,
            command=self._settings_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_choices,
            text="ジョイスティック",
            value="joystick",
            variable=self.control_mode_var,
            command=self._settings_changed,
        ).pack(side="left", padx=(12, 0))

        ttk.Label(settings, text="カーソル移動量").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            settings,
            from_=0.5,
            to=6.0,
            variable=self.gain_var,
            command=lambda _value: self._settings_changed(),
        ).grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.gain_label = ttk.Label(settings, width=5)
        self.gain_label.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        ttk.Label(settings, text="平滑化（右ほど滑らか）").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Scale(
            settings,
            from_=0.03,
            to=0.60,
            variable=self.smoothing_var,
            command=lambda _value: self._settings_changed(),
        ).grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.smoothing_label = ttk.Label(settings, width=7)
        self.smoothing_label.grid(row=2, column=2, padx=(8, 0), pady=(8, 0))

        ttk.Label(settings, text="反応開始荷重").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            settings,
            from_=0.05,
            to=3.0,
            variable=self.activation_weight_var,
            command=lambda _value: self._settings_changed(),
        ).grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.activation_weight_label = ttk.Label(settings, width=7)
        self.activation_weight_label.grid(row=3, column=2, padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(
            settings,
            text="踏み込みクリック",
            variable=self.impact_click_enabled_var,
            command=self._settings_changed,
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            settings,
            from_=1.0,
            to=15.0,
            variable=self.impact_click_rise_var,
            command=lambda _value: self._settings_changed(),
        ).grid(row=4, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.impact_click_rise_label = ttk.Label(settings, width=7)
        self.impact_click_rise_label.grid(row=4, column=2, padx=(8, 0), pady=(8, 0))

        toggles = ttk.Frame(settings)
        toggles.grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(
            toggles, text="左右反転", variable=self.invert_x_var, command=self._settings_changed
        ).pack(side="left")
        ttk.Checkbutton(
            toggles, text="上下反転", variable=self.invert_y_var, command=self._settings_changed
        ).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            toggles,
            text="静止クリック",
            variable=self.dwell_enabled_var,
            command=self._settings_changed,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(toggles, text="秒").pack(side="right")
        ttk.Spinbox(
            toggles,
            from_=0.3,
            to=5.0,
            increment=0.1,
            width=5,
            textvariable=self.dwell_seconds_var,
            command=self._settings_changed,
        ).pack(side="right", padx=(12, 3))
        settings.columnconfigure(1, weight=1)

        safety = ttk.LabelFrame(outer, text="安全と操作", padding=10)
        safety.pack(fill="x", pady=(12, 0))
        ttk.Label(
            safety,
            text=(
                "平らで滑らない場所に置き、最初は手すりや机につかまって試してください。\n"
                "ジョイスティックは足を置いて約0.5秒後に中心を取得します。クリックは軽い踏み増しです。"
            ),
            justify="left",
            wraplength=600,
        ).pack(anchor="w")

        self._refresh_setting_labels()

    def start(self) -> None:
        self._settings_changed()
        self.controller.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def stop(self) -> None:
        self.controller.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def recenter(self) -> None:
        if self.controller.recenter():
            self.detail_var.set("現在の足位置を新しい基準位置にしました。")
        else:
            messagebox.showinfo("移動基準", "ボードへ触れてから実行してください。", parent=self.root)

    def open_logs(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(self.log_path.parent)  # type: ignore[attr-defined]
        except OSError:
            subprocess.Popen(["explorer.exe", str(self.log_path.parent)])

    def close(self) -> None:
        self.controller.stop()
        self.root.destroy()

    def _settings_changed(self) -> None:
        try:
            self.settings = AppSettings(
                control_mode=self.control_mode_var.get(),
                gain=round(self.gain_var.get(), 2),
                smoothing=round(self.smoothing_var.get(), 2),
                activation_weight_kg=round(self.activation_weight_var.get(), 2),
                invert_x=self.invert_x_var.get(),
                invert_y=self.invert_y_var.get(),
                impact_click_enabled=self.impact_click_enabled_var.get(),
                impact_click_rise_kg=round(self.impact_click_rise_var.get(), 1),
                dwell_click_enabled=self.dwell_enabled_var.get(),
                dwell_seconds=round(self.dwell_seconds_var.get(), 2),
            )
            options = self.settings.to_trackpad_options()
            self.settings.save(self.settings_path)
            self.controller.update_options(options)
            self._refresh_setting_labels()
        except (ValueError, tk.TclError):
            return

    def _refresh_setting_labels(self) -> None:
        self.gain_label.configure(text=f"{self.gain_var.get():.1f}×")
        self.smoothing_label.configure(text=f"{self.smoothing_var.get():.2f} s")
        self.activation_weight_label.configure(text=f"{self.activation_weight_var.get():.2f} kg")
        self.impact_click_rise_label.configure(text=f"+{self.impact_click_rise_var.get():.1f} kg")

    def _enqueue_snapshot(self, snapshot: ControllerSnapshot) -> None:
        try:
            self.snapshot_queue.put_nowait(snapshot)
        except queue.Full:
            try:
                self.snapshot_queue.get_nowait()
            except queue.Empty:
                pass
            self.snapshot_queue.put_nowait(snapshot)

    def _drain_snapshots(self) -> None:
        latest: ControllerSnapshot | None = None
        while True:
            try:
                latest = self.snapshot_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._show_snapshot(latest)
        if self.root.winfo_exists():
            self.root.after(75, self._drain_snapshots)

    def _show_snapshot(self, snapshot: ControllerSnapshot) -> None:
        self.status_var.set(snapshot.message)
        self.detail_var.set(snapshot.detail)
        if snapshot.state == STATE_ACTIVE:
            self.status_label.configure(style="Good.TLabel")
        elif snapshot.state == STATE_ERROR:
            self.status_label.configure(style="Error.TLabel")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        elif snapshot.state == STATE_CONNECTING:
            self.status_label.configure(style="Status.TLabel")
        else:
            self.status_label.configure(style="Status.TLabel")
        if snapshot.device is not None:
            self.device_var.set(f"{snapshot.device.product} ({snapshot.device.identifier})")
        if snapshot.board_state is not None:
            state = snapshot.board_state
            self.weight_var.set(f"{state.weight_kg:.1f} kg")
            if state.on_board:
                self.cog_var.set(f"X {state.cog_x:+.3f} / Y {state.cog_y:+.3f}")
                self._draw_board(float(state.cog_x), float(state.cog_y))
            else:
                self.cog_var.set("待機中")
                self._draw_board(None, None)

    def _draw_board(self, cog_x: float | None, cog_y: float | None) -> None:
        width = max(self.canvas.winfo_width(), 300)
        height = max(self.canvas.winfo_height(), 150)
        self.canvas.delete("all")
        pad = 18
        self.canvas.create_rectangle(
            pad,
            pad,
            width - pad,
            height - pad,
            outline="#64748b",
            width=2,
        )
        self.canvas.create_line(width / 2, pad, width / 2, height - pad, fill="#cbd5e1")
        self.canvas.create_line(pad, height / 2, width - pad, height / 2, fill="#cbd5e1")
        if cog_x is None or cog_y is None:
            return
        x = pad + (max(-1.0, min(1.0, cog_x)) + 1.0) / 2.0 * (width - pad * 2)
        y = pad + (1.0 - (max(-1.0, min(1.0, cog_y)) + 1.0) / 2.0) * (height - pad * 2)
        radius = 10
        self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill="#0ea5e9")


def main() -> int:
    root = tk.Tk()
    TrackpadDashboard(root)
    root.mainloop()
    return 0
