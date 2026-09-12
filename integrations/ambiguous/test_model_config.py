"""The live bridge must override model metadata retained by resumed sessions."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bridge
import procurement


class BuyerModelConfigTests(unittest.TestCase):
    def test_dm_and_resumed_task_explicitly_pin_luna_max_and_direct_provider(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HERMES_HOME': directory}):
            for module in (bridge, procurement):
                process = SimpleNamespace(returncode=0, communicate=lambda timeout: ('fixture output', 'session_id: session-1\n'))
                with self.subTest(entrypoint=module.__name__), \
                        patch.object(module, 'load_personality', return_value='Test personality'), \
                        patch.object(module.subprocess, 'Popen', return_value=process) as launch:
                    if module is bridge:
                        with patch.object(bridge, 'extract_response', return_value='Ready.'):
                            bridge.run_hermes({'content': 'Continue.'}, [], Path(directory))
                    else:
                        state = {'task_id': 'task-1', 'hermes_session_id': 'stored-sol-session'}
                        with patch.object(procurement, 'run_snapshot', return_value=state), \
                                patch.object(procurement, 'task_response', return_value=('session-1', 'Ready.')):
                            procurement.invoke(state, Path(directory))
                    command = launch.call_args.args[0]
                    self.assertEqual(command[command.index('--model') + 1], 'gpt-5.6-luna')
                    self.assertEqual(command[command.index('--provider') + 1], 'takeoff-openai')
                    self.assertEqual(command[command.index('--reasoning') + 1], 'max')
                    if module is procurement:
                        self.assertEqual(command[command.index('--resume') + 1], 'stored-sol-session')


if __name__ == '__main__':
    unittest.main()
