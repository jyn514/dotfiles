"""Translate horizontal swipes into the mouse's Back/Forward buttons."""

from kittens.tui.handler import result_handler
from kitty.fast_data_types import PRESS, RELEASE, send_mouse_event


def main(args: list[str]) -> None:
    pass


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    button = {"back": 8, "forward": 9}[args[1]]
    window = boss.window_id_map.get(target_window_id)
    if window is None:
        return
    position = window.current_mouse_position()
    if position is None:
        return
    # Kitty encodes the application's selected mouse protocol and sends nothing
    # when it has not requested mouse input. Keep coordinates for tmux panes.
    for action in (PRESS, RELEASE):
        send_mouse_event(
            window.screen,
            position["cell_x"],
            position["cell_y"],
            button,
            action,
            0,
        )
