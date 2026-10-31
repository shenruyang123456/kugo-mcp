import unittest
from pathlib import Path
from unittest.mock import patch

from kugo_mcp import connection


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuse_does_not_launch_or_query_native(self):
        with patch.object(connection,'debug_available',return_value=True), patch.object(connection,'is_running',return_value=True), patch.object(connection,'client_ui_ready',return_value=True), patch.object(connection.subprocess,'Popen') as launch:
            result = await connection.connect(9225)
        self.assertFalse(result['launched'])
        launch.assert_not_called()

    async def test_start_has_three_second_quiet_period_and_stable_readiness(self):
        with patch.object(connection,'debug_available',side_effect=[False,True,True,True]), patch.object(connection,'is_running',return_value=False), patch.object(connection,'port_open',return_value=False), patch.object(connection,'client_ui_ready',return_value=True), patch('kugou_native_mcp.installation.find_executable',return_value=Path('KuGou.exe')), patch.object(connection.subprocess,'Popen') as launch, patch.object(connection.asyncio,'sleep') as sleep:
            result = await connection.connect(9225)
        self.assertTrue(result['launched'])
        launch.assert_called_once()
        self.assertEqual([c.args[0] for c in sleep.await_args_list], [3,2,2])

    async def test_normal_client_is_not_killed_or_relaunched(self):
        with patch.object(connection,'debug_available',return_value=False), patch.object(connection,'is_running',return_value=True), patch.object(connection.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError,'普通启动'):
                await connection.connect(9225)
        launch.assert_not_called()

    async def test_unrelated_occupied_port_does_not_launch(self):
        with patch.object(connection,'debug_available',return_value=False), patch.object(connection,'is_running',return_value=False), patch.object(connection,'port_open',return_value=True), patch.object(connection.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError,'占用'):
                await connection.connect(9225)
        launch.assert_not_called()
