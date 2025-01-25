#!/usr/bin/env python3

import argparse, os, subprocess, shutil
from pathlib import Path
from typing import List, Optional
from enum import Enum, auto

class Op(Enum):
  CREATE = auto()  # Create+start new container
  START = auto()   # Start existing container
  STOP = auto()    # Stop container
  RESTART = auto() # Restart container
  CLEAN = auto()   # Restart with cache clear
  RESET = auto()   # Remove and recreate
  NUKE = auto()    # Full rebuild

ROOT = Path(__file__).resolve().parent.parent
TMPL = ROOT/"drun"/"templates"
PROJ = ROOT/"projects"

ENV = {k: os.getenv(f"DOCKER_{k}", v) for k,v in {
  "USER": "developer", "PASS": "password", "WORKSPACE": "./workspace",
  "ROOT": "0", "PORTS": "", "STARTUP": None, "DEBUG": "0"
}.items()}

class Docker:
  def __init__(self, name: str, op: Op, user=None, pwd=None, ws=None,
               script=None, ports=None, root=None, debug=0):
    self.name = name
    self.op = op
    self.user = user or ENV["USER"]
    self.pwd = pwd or ENV["PASS"]
    self.ws = os.path.abspath(ws or ENV["WORKSPACE"])
    self.script = script or ENV["STARTUP"]
    self.root = root if root is not None else bool(int(ENV["ROOT"]))
    self.debug = int(ENV["DEBUG"]) if debug == 0 else debug
    self.dir = PROJ/name
    self.df = self.dir/"Dockerfile"

    self.ports = ports or []
    if not ports and ENV["PORTS"]:
      self.ports = [tuple(map(int, p.split(":"))) for p in ENV["PORTS"].split(",")]

  def dbg(self, lvl: int, msg: str):
    if self.debug >= lvl: print(f"[DEBUG-{lvl}] {msg}")

  def setup(self):
    if not self.dir.exists():
      self.dir.mkdir(parents=True)
    if not self.df.exists():
      shutil.copy2(TMPL/"Dockerfile.template", self.df)
      self.dbg(2, f"Created Dockerfile in {self.dir}")

  def exists(self) -> bool:
    try: return self.name in subprocess.run(
      ["docker", "ps", "-a", "--filter", f"name=^{self.name}$", "--format", "{{.Names}}"],
      capture_output=True, text=True).stdout
    except: return False

  def running(self) -> bool:
    try: return self.name in subprocess.run(
      ["docker", "ps", "--filter", f"name=^{self.name}$", "--format", "{{.Names}}"],
      capture_output=True, text=True).stdout
    except: return False

  def build(self) -> bool:
    self.dbg(2, f"Building from {self.df}...")
    try:
      subprocess.run(["docker", "build",
        "--build-arg", f"USERNAME={self.user}",
        "--build-arg", f"USER_PASSWORD={self.pwd}",
        "-t", self.name, "-f", str(self.df), str(self.dir)], check=True)
      self.dbg(2, "Build OK")
      return True
    except Exception as e:
      print(f"Build failed: {e}")
      return False

  def run_cmd(self) -> List[str]:
    cmd = ["docker", "run", "-d", "--name", self.name]
    cmd.extend(sum([("-p", f"{h}:{c}") for h,c in self.ports], ()))
    cmd.extend(["-v", f"{self.ws}:/home/{self.user}/workspace"])
    if not self.root: cmd.extend(["-u", self.user])
    return cmd + [self.name]

  def clear_cache(self):
    try:
      subprocess.run(["docker", "exec", self.name, "sync"], check=True)
      subprocess.run(["docker", "exec", self.name, "bash", "-c",
                    "echo 3 > /proc/sys/vm/drop_caches"], check=True)
      self.dbg(2, "Cache cleared")
    except Exception as e: print(f"Cache clear failed: {e}")

  def create(self):
    if not self.df.exists():
      print(f"No Dockerfile at {self.df}")
      return
    os.makedirs(self.ws, exist_ok=True)
    if not self.build(): return
    subprocess.run(self.run_cmd(), check=True)
    if self.script:
      subprocess.run(["docker", "exec", self.name, "bash", "-c",
        f"cd /home/{self.user}/workspace && ./{self.script}"], check=True)

  def run(self):
    try:
      self.setup()
      exists = self.exists()
      running = self.running()

      checks = {
        (Op.CREATE, exists): "exists. Use 'start' or 'reset'.",
        (Op.START, not exists or running): "'not found' if not exists else 'running'",
        (Op.STOP, not exists or not running): "'not found' if not exists else 'not running'",
        (Op.RESTART, not exists): "not found. Use 'create'.",
        (Op.CLEAN, not exists): "not found. Use 'create'."
      }

      for (op, cond), msg in checks.items():
        if self.op == op and cond:
          print(f"Container {self.name} {eval(msg) if '{' in msg else msg}")
          return

      ops = {
        Op.CREATE: lambda: self.create(),
        Op.START: lambda: subprocess.run(["docker", "start", self.name], check=True),
        Op.STOP: lambda: subprocess.run(["docker", "stop", self.name], check=True),
        Op.RESTART: lambda: subprocess.run(["docker", "restart", self.name], check=True),
        Op.CLEAN: lambda: [self.clear_cache(), subprocess.run(["docker", "restart", self.name], check=True)],
        Op.RESET: lambda: [subprocess.run(["docker", "stop" if running else "rm", self.name], check=True) if exists else None, self.create()],
        Op.NUKE: lambda: [subprocess.run(["docker", "stop" if running else "rm", self.name],
          check=True) if exists else None, subprocess.run(["docker", "rmi", self.name],
          check=True), self.create()]
      }[self.op]()

      print(f"Operation '{self.op.name.lower()}' completed!")

    except Exception as e:
      print(f"{'Error during' if isinstance(e, subprocess.CalledProcessError) else 'Unexpected'} error: {e}")

def main():
  p = argparse.ArgumentParser(description="Docker container management")
  p.add_argument("operation", choices=[op.name.lower() for op in Op])
  p.add_argument("container_name")
  p.add_argument("--username", help="Container username (env: DOCKER_USER)")
  p.add_argument("--password", help="User password (env: DOCKER_PASS)")
  p.add_argument("--workspace", help="Local workspace path (env: DOCKER_WORKSPACE)")
  p.add_argument("--startup-script", help="Startup script (env: DOCKER_STARTUP)")
  p.add_argument("--ports", nargs="+", help="Port forwards host:container (env: DOCKER_PORTS)")
  p.add_argument("--root", action="store_true", help="Root mode (env: DOCKER_ROOT)")
  p.add_argument("--debug", type=int, choices=range(5), default=0)

  args = p.parse_args()
  ports = [(int(h),int(c)) for p in (args.ports or []) for h,c in [p.split(":")]]

  Docker(
    name=args.container_name,
    op=Op[args.operation.upper()],
    user=args.username,
    pwd=args.password,
    ws=args.workspace,
    script=args.startup_script,
    ports=ports,
    root=args.root,
    debug=args.debug
  ).run()

if __name__ == "__main__":
  main()