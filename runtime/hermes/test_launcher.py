"""Host-side launcher boundary regressions; no Docker or credentials required."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


LAUNCHER = Path(__file__).resolve().parents[2] / 'scripts' / 'hermes'


class LauncherIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='takeoff-launcher-test-')
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)

    def launcher(self, name):
        root = self.scratch / name / 'repo'
        (root / 'scripts').mkdir(parents=True)
        (root / 'runtime/hermes').mkdir(parents=True)
        shutil.copyfile(LAUNCHER, root / 'scripts/hermes')
        (root / 'runtime/hermes/config.yaml').write_text('model: {}\n')
        (root / 'runtime/hermes/SOUL.md').write_text('Takeoff\n')
        (root / '.env.example').write_text('OPENAI_API_KEY=\n')
        loader = importlib.machinery.SourceFileLoader(name, str(root / 'scripts/hermes'))
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_dangling_state_file_symlinks_do_not_create_outside_targets(self):
        for name in ('config.yaml', '.env'):
            with self.subTest(path=name):
                launcher = self.launcher('dangling-' + name)
                launcher.STATE.mkdir(parents=True)
                outside = launcher.ROOT.parent / 'outside-target'
                (launcher.STATE / name).symlink_to(outside)
                with self.assertRaisesRegex(SystemExit, 'Refusing symlink'):
                    launcher.init()
                self.assertFalse(outside.exists())

    def test_existing_state_file_symlinks_preserve_outside_content_and_mode(self):
        for name in ('config.yaml', '.env'):
            with self.subTest(path=name):
                launcher = self.launcher('existing-' + name)
                launcher.STATE.mkdir(parents=True)
                outside = launcher.ROOT.parent / 'outside-target'
                outside.write_text('leave unchanged\n')
                outside.chmod(0o640)
                (launcher.STATE / name).symlink_to(outside)
                with self.assertRaisesRegex(SystemExit, 'Refusing symlink'):
                    launcher.init()
                self.assertEqual(outside.read_text(), 'leave unchanged\n')
                self.assertEqual(outside.stat().st_mode & 0o777, 0o640)

    def test_state_directory_symlinks_do_not_populate_outside_directory(self):
        for relative in ('.local', '.local/hermes', '.local/hermes/home'):
            with self.subTest(path=relative):
                launcher = self.launcher('directory-' + relative.replace('/', '-'))
                outside = launcher.ROOT.parent / 'outside-directory'
                outside.mkdir()
                marker = outside / 'untouched'
                marker.write_text('leave unchanged\n')
                redirected = launcher.ROOT / relative
                redirected.parent.mkdir(parents=True, exist_ok=True)
                redirected.symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(SystemExit, 'Refusing state outside repository'):
                    launcher.init()
                self.assertEqual(list(outside.iterdir()), [marker])
                self.assertEqual(marker.read_text(), 'leave unchanged\n')

    def test_pull_refuses_pin_symlink_before_docker_and_preserves_target(self):
        for existing in (False, True):
            with self.subTest(existing_target=existing):
                launcher = self.launcher('pin-' + str(existing))
                outside = launcher.ROOT.parent / 'outside-pin'
                if existing:
                    outside.write_text('leave unchanged\n')
                launcher.PIN.symlink_to(outside)
                with patch.object(launcher.sys, 'argv', ['hermes', 'pull']), \
                        patch.object(launcher, 'docker') as docker:
                    with self.assertRaisesRegex(SystemExit, 'Refusing image pin'):
                        launcher.main()
                    docker.assert_not_called()
                self.assertEqual(outside.exists(), existing)
                if existing:
                    self.assertEqual(outside.read_text(), 'leave unchanged\n')

    def test_pin_parent_symlink_is_refused(self):
        launcher = self.launcher('pin-parent')
        outside = launcher.ROOT.parent / 'outside-directory'
        outside.mkdir()
        (outside / 'image.txt').write_text('leave unchanged\n')
        (launcher.PIN.parent / 'config.yaml').unlink()
        (launcher.PIN.parent / 'SOUL.md').unlink()
        launcher.PIN.parent.rmdir()
        launcher.PIN.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(SystemExit, 'Refusing image pin'):
            launcher.validate_pin()
        self.assertEqual((outside / 'image.txt').read_text(), 'leave unchanged\n')

    def run_mocked(self, launcher, *, background=True, buyer_result=0,
                   status='stopped', fail_operation=None, voice_web=False):
        """Exercise command construction and resource lifetime without host Docker."""
        launcher.PIN.write_text('nousresearch/hermes-agent@sha256:' + 'a' * 64)
        commands = []

        def execute(command, **kwargs):
            commands.append(command)
            operation = command[1:3]
            if operation == ['inspect', launcher.BRIDGE_NAME + '-buyer']:
                return subprocess.CompletedProcess(command, 0, stdout=status + '\n')
            if fail_operation == operation:
                raise subprocess.CalledProcessError(1, command)
            code = buyer_result if operation == ['run', '--rm'] else 0
            return subprocess.CompletedProcess(command, code)

        def inspect(command, **kwargs):
            proxy_name = command[2]
            return json.dumps({proxy_name.removesuffix('-egress'): {'IPAddress': '172.20.0.2'}})

        with patch.object(launcher, 'docker', return_value=['docker']), \
                patch.object(launcher, 'owner', return_value=(1000, 1000)), \
                patch.object(launcher.subprocess, 'run', side_effect=execute), \
                patch.object(launcher.subprocess, 'check_output', side_effect=inspect):
            try:
                result = launcher.run(['exec', 'bridge.py'], background=background, voice_web=voice_web)
            except subprocess.CalledProcessError:
                if fail_operation is None:
                    raise
                result = 1
        return result, commands

    def test_background_success_keeps_buyer_proxy_and_network(self):
        launcher = self.launcher('background-success')
        result, commands = self.run_mocked(launcher)
        self.assertEqual(result, 0)
        buyer_index = next(i for i, command in enumerate(commands) if command[1:3] == ['run', '--rm'])
        self.assertIn('--detach', commands[buyer_index])
        self.assertEqual(buyer_index, len(commands) - 1)
        self.assertEqual(sum(command[1:3] == ['network', 'rm'] for command in commands), 1)

    def test_failed_background_start_removes_all_resources(self):
        launcher = self.launcher('background-failure')
        result, commands = self.run_mocked(launcher, buyer_result=125)
        self.assertEqual(result, 125)
        self.assertEqual(commands[-3:], [
            ['docker', 'rm', '-f', launcher.BRIDGE_NAME + '-buyer'],
            ['docker', 'rm', '-f', launcher.BRIDGE_NAME + '-egress'],
            ['docker', 'network', 'rm', launcher.BRIDGE_NAME],
        ])

    def test_partial_background_setup_failure_removes_resources(self):
        launcher = self.launcher('background-partial')
        result, commands = self.run_mocked(launcher, fail_operation=['network', 'connect'])
        self.assertEqual(result, 1)
        self.assertFalse(any(command[1:3] == ['run', '--rm'] for command in commands))
        self.assertEqual(commands[-3:], [
            ['docker', 'rm', '-f', launcher.BRIDGE_NAME + '-buyer'],
            ['docker', 'rm', '-f', launcher.BRIDGE_NAME + '-egress'],
            ['docker', 'network', 'rm', launcher.BRIDGE_NAME],
        ])

    def test_existing_background_buyer_is_not_replaced_or_duplicated(self):
        launcher = self.launcher('background-existing')
        result, commands = self.run_mocked(launcher, status='running')
        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1:3], ['inspect', launcher.BRIDGE_NAME + '-buyer'])

    def test_foreground_success_still_cleans_resources(self):
        launcher = self.launcher('foreground-success')
        result, commands = self.run_mocked(launcher, background=False)
        self.assertEqual(result, 0)
        buyer = next(command for command in commands if command[1:3] == ['run', '--rm'])
        self.assertNotIn('--detach', buyer)
        network = buyer[buyer.index('--network') + 1]
        self.assertNotEqual(network, launcher.BRIDGE_NAME)
        self.assertEqual(commands[-3:], [
            ['docker', 'rm', '-f', network + '-buyer'],
            ['docker', 'rm', '-f', network + '-egress'],
            ['docker', 'network', 'rm', network],
        ])

    def test_background_preserves_nonroot_readonly_repository_boundary(self):
        launcher = self.launcher('background-boundary')
        result, commands = self.run_mocked(launcher)
        self.assertEqual(result, 0)
        buyer = next(command for command in commands if command[1:3] == ['run', '--rm'])
        self.assertEqual(buyer[buyer.index('--user') + 1], '1000:1000')
        for flag in ('--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--dns=127.0.0.1'):
            self.assertIn(flag, buyer)
        mounts = [buyer[i + 1] for i, value in enumerate(buyer) if value == '--mount']
        self.assertEqual(mounts, [
            f'type=bind,src={launcher.ROOT},dst=/workspace,readonly',
            f'type=bind,src={launcher.STATE},dst=/workspace/.local/hermes',
            f'type=bind,src={launcher.STATE},dst=/opt/data',
        ])
        network = next(command for command in commands if command[1:3] == ['network', 'create'])
        self.assertIn('--internal', network)
        self.assertIn('com.docker.network.bridge.gateway_mode_ipv4=isolated', network)

    def test_voice_web_publishes_only_loopback_on_credential_free_relay(self):
        launcher = self.launcher('voice-boundary')
        result, commands = self.run_mocked(launcher, background=False, voice_web=True)
        self.assertEqual(result, 0)
        buyer = next(c for c in commands if c[1:3] == ['run', '--rm'])
        proxy = next(c for c in commands if c[1:3] == ['run', '--detach'])
        self.assertNotIn('--publish', buyer)
        self.assertEqual(proxy[proxy.index('--publish') + 1], '127.0.0.1:3000:3000/tcp')
        self.assertEqual(sum(c.count('--publish') for c in commands), 1)
        self.assertEqual(proxy[proxy.index('--network=bridge')], '--network=bridge')
        self.assertEqual(proxy[-1], buyer[buyer.index('--name') + 1])
        self.assertEqual(proxy[-2], launcher.VOICE_RELAY)
        self.assertEqual([proxy[i + 1] for i, arg in enumerate(proxy) if arg == '--mount'],
                         [f'type=bind,src={launcher.ROOT / "runtime/hermes/egress.py"},dst=/egress.py,readonly'])
        self.assertNotIn('--env-file', proxy)
        self.assertNotIn('--env', proxy)
        for flag in ('--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--dns=127.0.0.1'):
            self.assertIn(flag, buyer)
        self.assertIn('PYTHONPATH=/workspace', buyer)
        self.assertIn('TAKEOFF_VOICE_HOME=/workspace/.local/hermes/voice', buyer)
        self.assertIn(f'type=bind,src={launcher.ROOT},dst=/workspace,readonly', buyer)
        self.assertEqual(buyer[buyer.index('--user') + 1], '1000:1000')
        network = next(c for c in commands if c[1:3] == ['network', 'create'])
        self.assertIn('--internal', network)
        self.assertIn('com.docker.network.bridge.gateway_mode_ipv4=isolated', network)
        network_name = buyer[buyer.index('--network') + 1]
        self.assertNotEqual(network_name, launcher.BRIDGE_NAME)
        self.assertEqual(commands[-3:], [
            ['docker', 'rm', '-f', network_name + '-buyer'],
            ['docker', 'rm', '-f', network_name + '-egress'],
            ['docker', 'network', 'rm', network_name]])

    def test_voice_web_bind_failure_cleans_its_own_network(self):
        launcher = self.launcher('voice-publish-failure')
        result, commands = self.run_mocked(launcher, background=False, voice_web=True,
                                           fail_operation=['run', '--detach'])
        self.assertEqual(result, 1)
        self.assertFalse(any(c[1:3] == ['run', '--rm'] for c in commands))
        self.assertEqual(commands[-1][1:3], ['network', 'rm'])
        self.assertNotEqual(commands[-1][-1], launcher.BRIDGE_NAME)

    def test_voice_web_command_runs_module_and_disallows_port_overrides(self):
        launcher = self.launcher('voice-command')
        with patch.object(launcher.sys, 'argv', ['hermes', 'voice-web', '--request', '/workspace/.local/hermes/voice/request.json']), \
                patch.object(launcher, 'run', return_value=0) as run:
            self.assertEqual(launcher.main(), 0)
            run.assert_called_once_with(['exec', '/opt/hermes/.venv/bin/python', '-u', '-m',
                'integrations.voice.human_call', '--request', '/workspace/.local/hermes/voice/request.json',
                '--bind', '0.0.0.0', '--port', '3000'], voice_web=True)
        for option in ('--bind', '--bind=0.0.0.0', '--port', '--port=8080'):
            with self.subTest(option=option), patch.object(launcher.sys, 'argv', ['hermes', 'voice-web', option]), \
                    patch.object(launcher, 'run') as run:
                with self.assertRaisesRegex(SystemExit, '127.0.0.1:3000'):
                    launcher.main()
                run.assert_not_called()

    def test_voice_relay_has_one_fixed_upstream_and_reuses_reviewed_proxy(self):
        from unittest.mock import MagicMock
        launcher = self.launcher('voice-relay')
        class InertServer:
            def __init__(self, address, handler=None):
                self.address = address
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def serve_forever(self):
                pass
        tunnel = MagicMock()
        egress = {'ProxyServer': InertServer, 'tunnel': tunnel}
        with patch('runpy.run_path', return_value=egress) as load, \
                patch('socketserver.TCPServer', InertServer), patch('threading.Thread'), \
                patch('sys.argv', ['relay', 'takeoff-voice-buyer']):
            namespace = {}
            exec(compile(launcher.VOICE_RELAY, '<voice-relay>', 'exec'), namespace)
            load.assert_called_once_with('/egress.py')
        handler = object.__new__(namespace['Handler'])
        handler.request = MagicMock()
        with patch('socket.create_connection') as connect:
            handler.handle()
            connect.assert_called_once_with(('takeoff-voice-buyer', 3000), timeout=10)
            tunnel.assert_called_once_with(handler.request, connect.return_value.__enter__.return_value)

    def test_root_launch_uses_sudo_caller_and_preserves_state_ownership(self):
        launcher = self.launcher('root-caller')
        with patch.object(launcher.os, 'getuid', return_value=0), \
                patch.dict(launcher.os.environ, {'SUDO_UID': '1234', 'SUDO_GID': '5678'}), \
                patch.object(launcher.os, 'chown') as chown:
            self.assertEqual(launcher.owner(), (1234, 5678))
            launcher.init()
        self.assertEqual(chown.call_count, 8)
        for call in chown.call_args_list:
            self.assertTrue(call.args[0].is_relative_to(launcher.ROOT))
            self.assertEqual(call.args[1:], (1234, 5678))
            self.assertEqual(call.kwargs, {'follow_symlinks': False})

    def test_root_identity_is_rejected(self):
        launcher = self.launcher('root-refused')
        with patch.object(launcher.os, 'getuid', return_value=0), \
                patch.dict(launcher.os.environ, {'SUDO_UID': '0', 'SUDO_GID': '0'}):
            with self.assertRaisesRegex(SystemExit, 'non-root'):
                launcher.owner()


if __name__ == '__main__':
    unittest.main()
