"""Background board-to-pointer controller used by CLI and dashboard."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .device import BalanceBoardDevice, DeviceInfo, enumerate_devices, select_balance_board
from .pointer import PointerFrame, TrackpadOptions, TrackpadProcessor, WindowsPointer
from .reports import BoardState


STATE_STOPPED = "stopped"
STATE_CONNECTING = "connecting"
STATE_ACTIVE = "active"
STATE_ERROR = "error"


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    state: str
    message: str
    detail: str = ""
    device: DeviceInfo | None = None
    board_state: BoardState | None = None
    pointer_frame: PointerFrame | None = None


SnapshotCallback = Callable[[ControllerSnapshot], None]


class TrackpadController:
    def __init__(
        self,
        options: TrackpadOptions,
        *,
        on_snapshot: SnapshotCallback | None = None,
        logger: logging.Logger | None = None,
        pointer: WindowsPointer | None = None,
    ) -> None:
        self._options = options
        self._on_snapshot = on_snapshot
        self._logger = logger or logging.getLogger(__name__)
        self._pointer = pointer or WindowsPointer()
        self._processor = TrackpadProcessor(options)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="WiiFitTrackpad", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self._thread = None
        self._emit(ControllerSnapshot(STATE_STOPPED, "停止中"))

    def update_options(self, options: TrackpadOptions) -> None:
        options.validate()
        with self._lock:
            self._options = options
            self._processor.set_options(options)

    def recenter(self) -> bool:
        with self._lock:
            return self._processor.recenter()

    def _run(self) -> None:
        self._emit(ControllerSnapshot(STATE_CONNECTING, "ボードを探しています…"))
        try:
            info = select_balance_board(enumerate_devices())
            self._logger.info("Opening %s %s (%s)", info.manufacturer, info.product, info.identifier)
            self._emit(
                ControllerSnapshot(
                    STATE_CONNECTING,
                    "初期化しています…",
                    f"{info.manufacturer} {info.product}",
                    device=info,
                )
            )
            with BalanceBoardDevice(info) as board:
                board.initialize()
                self._emit(
                    ControllerSnapshot(
                        STATE_ACTIVE,
                        "カーソル操作中",
                        (
                            "足を置いて約0.5秒待つと、その位置を中心にして動かせます。"
                            if self._options.control_mode == "joystick"
                            else "足を動かした差分だけカーソルが動きます。"
                        ),
                        device=info,
                    )
                )
                for state in board.states(stop_event=self._stop_event):
                    with self._lock:
                        frame = self._processor.update(state)
                    if frame.active and (frame.delta_x or frame.delta_y):
                        self._pointer.move_relative(frame.delta_x, frame.delta_y)
                    if frame.click:
                        self._pointer.click_left()
                        self._logger.info("Left click: %s", frame.click_reason)
                    self._emit(
                        ControllerSnapshot(
                            STATE_ACTIVE,
                            "カーソル操作中",
                            "荷重を検出" if frame.active else "待機中 — ボードへ触れてください",
                            device=info,
                            board_state=state,
                            pointer_frame=frame,
                        )
                    )
        except Exception as error:
            if not self._stop_event.is_set():
                self._logger.exception("Trackpad controller stopped")
                self._emit(ControllerSnapshot(STATE_ERROR, "接続できませんでした", str(error)))
        finally:
            if self._stop_event.is_set():
                self._emit(ControllerSnapshot(STATE_STOPPED, "停止中"))

    def _emit(self, snapshot: ControllerSnapshot) -> None:
        if self._on_snapshot is not None:
            self._on_snapshot(snapshot)
