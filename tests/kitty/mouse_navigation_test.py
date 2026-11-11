"""Check navigation buttons, pointer coordinates, and kitten target selection.

These unit tests replace Kitty's native API; live Kitty/tmux delivery needs a
host check. Mouse button 8/9 numbering follows Kitty's documented kitten API.
"""

import runpy
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch


KITTEN = Path(__file__).resolve().parents[2] / "config/kitty/mouse_navigation.py"


class MouseNavigationTest(unittest.TestCase):
    def setUp(self):
        native = ModuleType("kitty.fast_data_types")
        native.PRESS = object()
        native.RELEASE = object()
        native.send_mouse_event = Mock()
        handler = ModuleType("kittens.tui.handler")
        handler.result_handler = lambda **kwargs: lambda function: function
        with patch.dict(sys.modules, {
            "kitty.fast_data_types": native,
            "kittens.tui.handler": handler,
        }):
            self.handle_result = runpy.run_path(str(KITTEN))["handle_result"]
        self.native = native
        self.window = SimpleNamespace(
            screen=object(),
            current_mouse_position=lambda: {"cell_x": 37, "cell_y": 12},
        )
        self.boss = SimpleNamespace(
            window_id_map={42: self.window},
            active_window=SimpleNamespace(screen=object()),
        )

    def test_sends_back_and_forward_clicks_to_the_target_not_the_active_window(self):
        for direction, button in (("back", 8), ("forward", 9)):
            with self.subTest(direction=direction):
                self.native.send_mouse_event.reset_mock()
                self.handle_result([str(KITTEN), direction], None, 42, self.boss)
                self.assertEqual(self.native.send_mouse_event.call_args_list, [
                    call(self.window.screen, 37, 12, button, self.native.PRESS, 0),
                    call(self.window.screen, 37, 12, button, self.native.RELEASE, 0),
                ])

    def test_uses_the_current_pointer_position_on_each_swipe(self):
        self.handle_result([str(KITTEN), "back"], None, 42, self.boss)
        self.native.send_mouse_event.reset_mock()
        self.window.current_mouse_position = lambda: {"cell_x": 81, "cell_y": 3}
        self.handle_result([str(KITTEN), "forward"], None, 42, self.boss)
        self.native.send_mouse_event.assert_has_calls([
            call(self.window.screen, 81, 3, 9, self.native.PRESS, 0),
            call(self.window.screen, 81, 3, 9, self.native.RELEASE, 0),
        ])

    def test_closed_window_does_not_send_to_another_window(self):
        self.handle_result([str(KITTEN), "back"], None, 99, self.boss)
        self.native.send_mouse_event.assert_not_called()

    def test_missing_pointer_position_does_not_send_a_click_at_an_invented_position(self):
        self.window.current_mouse_position = lambda: None
        self.handle_result([str(KITTEN), "forward"], None, 42, self.boss)
        self.native.send_mouse_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
