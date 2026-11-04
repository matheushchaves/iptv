"""Testes da conversa do vigia com o sistema: Mac acordado, nome na rede, bateria e início no login."""
import io
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import vigia_system
from vigia_system import KeepAwake, NamePublisher, internet_ok, lan_ip, launch_agent_plist, on_battery

ROOT = Path(__file__).parent


class FakeProc:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


class Recorder:
    def __init__(self):
        self.calls, self.procs = [], []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.procs.append(FakeProc())
        return self.procs[-1]


class KeepAwakeTest(unittest.TestCase):
    def test_holds_the_mac_only_while_on(self):
        popen = Recorder()
        awake = KeepAwake(popen=popen, enabled=True)
        awake.set(True)
        awake.set(True)
        self.assertEqual(popen.calls, [["caffeinate", "-s", "-w", str(os.getpid())]])
        awake.set(False)
        self.assertFalse(popen.procs[0].alive)

    def test_comes_back_if_caffeinate_died(self):
        popen = Recorder()
        awake = KeepAwake(popen=popen, enabled=True)
        awake.set(True)
        popen.procs[0].alive = False
        awake.set(True)
        self.assertEqual(len(popen.calls), 2)

    def test_does_nothing_outside_the_mac(self):
        popen = Recorder()
        KeepAwake(popen=popen, enabled=False).set(True)
        self.assertEqual(popen.calls, [])

    def test_missing_program_is_tried_only_once(self):
        calls = []

        def missing(args, **kwargs):
            calls.append(args)
            raise FileNotFoundError(args[0])
        awake = KeepAwake(popen=missing, enabled=True)
        with redirect_stdout(io.StringIO()):
            awake.set(True)
            awake.set(True)
        self.assertEqual(len(calls), 1)


class NamePublisherTest(unittest.TestCase):
    def test_publishes_and_republishes_when_ip_changes(self):
        popen = Recorder()
        names = NamePublisher(8000, popen=popen, enabled=True)
        names.update("192.168.0.4")
        names.update("192.168.0.4")
        names.update("192.168.0.10")
        self.assertEqual(popen.calls[-1],
                         ["dns-sd", "-P", "Sofa", "_http._tcp", "local", "8000", "sofa.local", "192.168.0.10"])
        self.assertEqual(len(popen.calls), 2)
        self.assertFalse(popen.procs[0].alive)
        self.assertEqual(names.name, "sofa.local")

    def test_republishes_if_dns_sd_died(self):
        popen = Recorder()
        names = NamePublisher(8000, popen=popen, enabled=True)
        names.update("192.168.0.4")
        popen.procs[0].alive = False
        names.update("192.168.0.4")
        self.assertEqual(len(popen.calls), 2)

    def test_no_network_stops_publishing(self):
        popen = Recorder()
        names = NamePublisher(8000, popen=popen, enabled=True)
        names.update("192.168.0.4")
        names.update(None)
        self.assertFalse(popen.procs[0].alive)
        self.assertIsNone(names.name)

    def test_name_is_none_outside_the_mac(self):
        names = NamePublisher(8000, popen=Recorder(), enabled=False)
        names.update("192.168.0.4")
        self.assertIsNone(names.name)


class BatteryTest(unittest.TestCase):
    def batt(self, text):
        return on_battery(run=lambda *a, **k: mock.Mock(stdout=text, returncode=0))

    def test_reads_power_source(self):
        with mock.patch.object(vigia_system, "IS_MAC", True):
            self.assertTrue(self.batt("Now drawing from 'Battery Power'\n"))
            self.assertFalse(self.batt("Now drawing from 'AC Power'\n"))

    def test_failed_command_counts_as_plugged_in(self):
        def broken(*args, **kwargs):
            raise OSError("sem pmset")
        with mock.patch.object(vigia_system, "IS_MAC", True):
            self.assertFalse(on_battery(run=broken))

    def test_outside_the_mac_counts_as_plugged_in(self):
        with mock.patch.object(vigia_system, "IS_MAC", False):
            self.assertFalse(self.batt("Now drawing from 'Battery Power'\n"))


class NetworkTest(unittest.TestCase):
    def test_no_network_has_no_lan_ip(self):
        with mock.patch("socket.socket") as sock:
            sock.return_value.__enter__.return_value.connect.side_effect = OSError("sem rede")
            self.assertIsNone(lan_ip())

    def test_one_answer_is_enough_for_internet(self):
        hosts = []

        def connect(address, timeout):
            hosts.append(address)
            if address[0] == "1.1.1.1":
                raise OSError("bloqueado")
            return mock.MagicMock()
        self.assertTrue(internet_ok(connect=connect))
        self.assertEqual(hosts, [("1.1.1.1", 443), ("8.8.8.8", 443)])

    def test_no_answer_is_no_internet(self):
        def connect(address, timeout):
            raise OSError("sem rede")
        self.assertFalse(internet_ok(connect=connect))


class PlistTest(unittest.TestCase):
    def test_vigia_stays_alive_and_runs_in_the_project(self):
        plist = plistlib.loads(launch_agent_plist("local.sofa.vigia", ["/py", "vigia.py"], Path("/a & b"),
                                                  True, Path("/a & b/vigia.log")))
        self.assertEqual(plist["ProgramArguments"], ["/py", "vigia.py"])
        self.assertEqual(plist["WorkingDirectory"], "/a & b")
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])
        self.assertEqual(plist["ProcessType"], "Interactive")  # Background limitaria o proxy de vídeo
        self.assertEqual(plist["StandardErrorPath"], "/a & b/vigia.log")

    def test_app_does_not_come_back_after_quitting(self):
        plist = plistlib.loads(launch_agent_plist("local.sofa.barra", ["/app", "--barra"], Path("/a"), False))
        self.assertFalse(plist["KeepAlive"])
        self.assertNotIn("StandardErrorPath", plist)

    def run_cli(self, *args):
        done = subprocess.run([sys.executable, "vigia_system.py", *args], cwd=ROOT, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return plistlib.loads(done.stdout)

    def test_vigia_plist_uses_the_given_python(self):
        plist = self.run_cli("vigia-plist", "/opt/homebrew/bin/python3")
        self.assertEqual(plist["ProgramArguments"], ["/opt/homebrew/bin/python3", "vigia.py"])
        self.assertEqual(plist["WorkingDirectory"], str(ROOT.resolve()))
        self.assertEqual(plist["Label"], "local.sofa.vigia")

    def test_app_plist_starts_only_the_icon(self):
        plist = self.run_cli("app-plist", "/Apps/Sofá.app/Contents/MacOS/Sofa")
        self.assertEqual(plist["ProgramArguments"], ["/Apps/Sofá.app/Contents/MacOS/Sofa", "--barra"])
        self.assertEqual(plist["Label"], "local.sofa.barra")


class InstallerGuardTest(unittest.TestCase):
    def test_refuses_protected_folders(self):
        for folder in ("Downloads", "Documents", "Desktop"):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as home:
                project = Path(home) / folder / "iptv"
                project.mkdir(parents=True)
                shutil.copy(ROOT / "instalar-mac.sh", project)
                done = subprocess.run(["sh", "instalar-mac.sh"], cwd=project, env={**os.environ, "HOME": home},
                                      capture_output=True, text=True)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("mova a pasta", done.stdout + done.stderr)
                self.assertFalse((Path(home) / "Library" / "LaunchAgents").exists())


if __name__ == "__main__":
    unittest.main()
