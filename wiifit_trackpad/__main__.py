"""Command-line tools and dashboard launcher."""

from __future__ import annotations

import argparse
import sys
from threading import Event
from time import monotonic

from .controller import STATE_ERROR, ControllerSnapshot, TrackpadController
from .device import BalanceBoardDevice, enumerate_devices, select_balance_board
from .logging_setup import configure_logging
from .paths import user_log_path, user_settings_path
from .settings import AppSettings


def _configure_utf8_console() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def list_devices() -> int:
    devices = enumerate_devices()
    if not devices:
        print("Nintendo Wii HID (057E:0306) は見つかりませんでした。")
        return 1
    for index, device in enumerate(devices):
        kind = "Balance Board" if device.is_named_balance_board else "Balance Board候補"
        print(f"[{index}] {kind}: {device.manufacturer} {device.product} ({device.identifier})")
    return 0


def monitor(seconds: float | None) -> int:
    try:
        info = select_balance_board()
        deadline = monotonic() + seconds if seconds is not None else None
        print(f"接続: {info.manufacturer} {info.product} ({info.identifier})")
        print("Ctrl+C で終了")
        with BalanceBoardDevice(info) as board:
            board.initialize()
            for state in board.states(deadline=deadline):
                if state.on_board:
                    print(
                        f"weight={state.weight_kg:6.2f} kg  "
                        f"cog=({state.cog_x:+.4f}, {state.cog_y:+.4f})  "
                        f"button={'DOWN' if state.board_button_pressed else 'up'}"
                    )
                else:
                    print(f"weight={state.weight_kg:6.2f} kg  off-board")
    except KeyboardInterrupt:
        print("\n終了しました。")
    except (OSError, ValueError, TimeoutError) as error:
        print(f"ボードを開けませんでした: {error}", file=sys.stderr)
        return 2
    return 0


def run_headless(seconds: float | None) -> int:
    settings = AppSettings.load(user_settings_path())
    logger = configure_logging(user_log_path())
    stop_event = Event()
    exit_code = 0

    def show(snapshot: ControllerSnapshot) -> None:
        nonlocal exit_code
        if snapshot.board_state is None:
            print(f"{snapshot.message}: {snapshot.detail}".rstrip(": "))
        if snapshot.state == STATE_ERROR:
            exit_code = 2
            stop_event.set()

    controller = TrackpadController(
        settings.to_trackpad_options(),
        on_snapshot=show,
        logger=logger,
    )
    controller.start()
    started = monotonic()
    try:
        while not stop_event.wait(0.1):
            if seconds is not None and monotonic() - started >= seconds:
                break
            if not controller.running:
                break
    except KeyboardInterrupt:
        print("\n終了しました。")
    finally:
        controller.stop()
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wii Fit Balance Board 巨大トラックパッド")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("gui", help="ダッシュボードを開く")
    subparsers.add_parser("list", help="Nintendo HIDを一覧表示")
    monitor_parser = subparsers.add_parser("monitor", help="荷重と重心を表示（マウス操作なし）")
    monitor_parser.add_argument("--seconds", type=float)
    run_parser = subparsers.add_parser("run", help="GUIなしでトラックパッドを開始")
    run_parser.add_argument("--seconds", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return list_devices()
    if args.command == "monitor":
        return monitor(args.seconds)
    if args.command == "run":
        return run_headless(args.seconds)
    from .app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
