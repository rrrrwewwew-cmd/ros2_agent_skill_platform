"""No-shell build, test, and simulation gates for generated candidates."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic


class SandboxGateError(RuntimeError):
    """Report a failed or unavailable candidate validation gate."""


def _bounded_output(completed):
    text = f'{completed.stdout}\n{completed.stderr}'.strip()
    return text[-4000:]


class CandidateSandbox:
    """Execute fixed compiler/test commands inside one candidate root."""

    def __init__(self, runner=subprocess.run, timeout_sec=180.0):
        if not 10.0 <= float(timeout_sec) <= 600.0:
            raise SandboxGateError('sandbox timeout must be in [10, 600]')
        self.runner = runner
        self.timeout_sec = float(timeout_sec)

    @staticmethod
    def _environment():
        environment = dict(os.environ)
        for name in (
            'MIMO_API_KEY',
            'HTTP_PROXY',
            'HTTPS_PROXY',
            'ALL_PROXY',
            'http_proxy',
            'https_proxy',
            'all_proxy',
        ):
            environment.pop(name, None)
        environment.update({
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONNOUSERSITE': '1',
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
        })
        return environment

    def _run(self, command, root, environment_overrides=None):
        started = monotonic()
        environment = self._environment()
        environment.update(environment_overrides or {})
        try:
            completed = self.runner(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_sec,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                'returncode': None,
                'duration_ms': round((monotonic() - started) * 1000.0, 3),
                'output_tail': str(error)[-1000:],
                'output_sha256': hashlib.sha256(
                    str(error).encode('utf-8')
                ).hexdigest(),
            }
        output = _bounded_output(completed)
        return {
            'returncode': completed.returncode,
            'duration_ms': round((monotonic() - started) * 1000.0, 3),
            'output_tail': output,
            'output_sha256': hashlib.sha256(
                output.encode('utf-8')
            ).hexdigest(),
        }

    def validate(self, candidate):
        """Run compile, colcon build, unit tests, then simulation fixtures."""
        root = Path(candidate['root'])
        package = candidate['package_name']
        package_root = root / 'src' / package
        build = self._run([
            sys.executable,
            '-m',
            'compileall',
            '-q',
            str(package_root),
        ], root)
        if build['returncode'] != 0:
            return {'build': build}
        colcon = self._run([
            'colcon',
            '--log-base',
            'log',
            'build',
            '--base-paths',
            'src',
            '--build-base',
            'build',
            '--install-base',
            'install',
            '--packages-select',
            package,
            '--event-handlers',
            'console_direct+',
        ], root)
        build['colcon'] = colcon
        if colcon['returncode'] != 0:
            build['returncode'] = colcon['returncode']
            return {'build': build}
        unit_test = self._run([
            sys.executable,
            '-m',
            'pytest',
            '-q',
            str(package_root / 'test'),
            '-k',
            'not simulation',
        ], root, {'PYTHONPATH': str(package_root)})
        if unit_test['returncode'] != 0:
            return {'build': build, 'unit_test': unit_test}
        simulation = self._run([
            sys.executable,
            '-m',
            'pytest',
            '-q',
            str(package_root / 'test'),
            '-k',
            'simulation',
        ], root, {'PYTHONPATH': str(package_root)})
        return {
            'build': build,
            'unit_test': unit_test,
            'simulation': simulation,
        }
