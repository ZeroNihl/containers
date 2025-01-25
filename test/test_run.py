import unittest
from unittest.mock import patch, MagicMock, call
import sys
from pathlib import Path
import shutil
import os

sys.path.append(str(Path(__file__).resolve().parent.parent))
from drun.run import Docker, Op

class TestDockerManager(unittest.TestCase):
  def setUp(self):
    self.test_dir = Path("test_workspace")
    self.docker = Docker(
      name="test-container",
      op=Op.CREATE,
      user="testuser",
      pwd="testpass",
      ws=str(self.test_dir),
      debug=2
    )
    # Create test workspace
    self.test_dir.mkdir(exist_ok=True)

  def tearDown(self):
    # Clean up test directories and files
    if self.test_dir.exists():
      shutil.rmtree(self.test_dir)
    if self.docker.dir.exists():
      shutil.rmtree(self.docker.dir)

  @patch('subprocess.run')
  def test_container_state_checks(self, mock_run):
    # Test container existence check
    mock_run.return_value = MagicMock(stdout="test-container\n")
    self.assertTrue(self.docker.exists())

    mock_run.return_value = MagicMock(stdout="")
    self.assertFalse(self.docker.exists())

    # Test running state check
    mock_run.return_value = MagicMock(stdout="test-container\n")
    self.assertTrue(self.docker.running())

    mock_run.return_value = MagicMock(stdout="")
    self.assertFalse(self.docker.running())

  @patch('subprocess.run')
  @patch('shutil.copy2')
  def test_setup(self, mock_copy, mock_run):
    self.docker.setup()
    mock_copy.assert_called_once()
    self.assertTrue(self.docker.dir.exists())

  @patch('subprocess.run')
  def test_create_operation(self, mock_run):
      # Setup mock returns for all expected calls
      mock_run.side_effect = [
        MagicMock(stdout=""),           # exists check
        MagicMock(stdout=""),           # running check
        MagicMock(returncode=0),        # build command
        MagicMock(returncode=0)         # run command
      ]

      # Test CREATE operation
      self.docker.op = Op.CREATE
      self.docker.run()

      # Verify build and run commands were called (they will be calls 2 and 3)
      build_call = mock_run.call_args_list[2][0][0]
      self.assertEqual(build_call[0:2], ["docker", "build"])

      run_call = mock_run.call_args_list[3][0][0]
      self.assertEqual(run_call[0:2], ["docker", "run"])

  @patch('subprocess.run')
  def test_start_operation(self, mock_run):
    # Setup for START operation
    mock_run.side_effect = [
      MagicMock(stdout="test-container\n"),  # exists check
      MagicMock(stdout=""),                  # running check
      MagicMock(returncode=0)               # start command
    ]

    self.docker.op = Op.START
    self.docker.run()

    # Verify start command was called
    start_call = mock_run.call_args_list[-1]
    self.assertEqual(start_call[0][0], ["docker", "start", "test-container"])

  @patch('subprocess.run')
  def test_stop_operation(self, mock_run):
    # Setup for STOP operation
    mock_run.side_effect = [
      MagicMock(stdout="test-container\n"),  # exists check
      MagicMock(stdout="test-container\n"),  # running check
      MagicMock(returncode=0)               # stop command
    ]

    self.docker.op = Op.STOP
    self.docker.run()

    # Verify stop command was called
    stop_call = mock_run.call_args_list[-1]
    self.assertEqual(stop_call[0][0], ["docker", "stop", "test-container"])

  @patch('subprocess.run')
  def test_reset_operation(self, mock_run):
    # Setup for RESET operation
    mock_run.side_effect = [
      MagicMock(stdout="test-container\n"),  # exists check
      MagicMock(stdout="test-container\n"),  # running check
      MagicMock(returncode=0),              # stop command
      MagicMock(returncode=0),              # build command
      MagicMock(returncode=0)               # run command
    ]

    self.docker.op = Op.RESET
    self.docker.run()

    # Verify sequence of commands
    calls = mock_run.call_args_list
    self.assertEqual(calls[-3][0][0][0:2], ["docker", "stop"])
    self.assertEqual(calls[-2][0][0][0:2], ["docker", "build"])
    self.assertEqual(calls[-1][0][0][0:2], ["docker", "run"])

  @patch('subprocess.run')
  def test_nuke_operation(self, mock_run):
    # Setup for NUKE operation
    mock_run.side_effect = [
      MagicMock(stdout="test-container\n"),  # exists check
      MagicMock(stdout="test-container\n"),  # running check
      MagicMock(returncode=0),              # stop command
      MagicMock(returncode=0),              # rmi command
      MagicMock(returncode=0),              # build command
      MagicMock(returncode=0)               # run command
    ]

    self.docker.op = Op.NUKE
    self.docker.run()

    # Verify sequence of commands
    calls = mock_run.call_args_list
    self.assertEqual(calls[-4][0][0][0:2], ["docker", "stop"])
    self.assertEqual(calls[-3][0][0][0:2], ["docker", "rmi"])
    self.assertEqual(calls[-2][0][0][0:2], ["docker", "build"])
    self.assertEqual(calls[-1][0][0][0:2], ["docker", "run"])

  @patch('subprocess.run')
  def test_clean_operation(self, mock_run):
    # Setup for CLEAN operation
    mock_run.side_effect = [
      MagicMock(stdout="test-container\n"),  # exists check
      MagicMock(stdout="test-container\n"),  # running check
      MagicMock(returncode=0),              # sync command
      MagicMock(returncode=0),              # cache clear command
      MagicMock(returncode=0)               # restart command
    ]

    self.docker.op = Op.CLEAN
    self.docker.run()

    # Verify cache clear and restart commands
    calls = mock_run.call_args_list
    self.assertEqual(calls[-3][0][0], ["docker", "exec", "test-container", "sync"])
    self.assertEqual(calls[-1][0][0], ["docker", "restart", "test-container"])

  def test_run_cmd_generation(self):
    # Test port forwarding
    self.docker.ports = [(8080, 80), (2222, 22)]
    cmd = self.docker.run_cmd()
    self.assertIn("-p", cmd)
    self.assertIn("8080:80", cmd)
    self.assertIn("2222:22", cmd)

    # Test root user
    self.docker.root = True
    cmd = self.docker.run_cmd()
    self.assertNotIn("-u", cmd)

    # Test non-root user
    self.docker.root = False
    cmd = self.docker.run_cmd()
    self.assertIn("-u", cmd)
    self.assertIn("testuser", cmd)

if __name__ == '__main__':
  unittest.main(verbosity=2)