#!/usr/bin/env python3
import os
import signal

pid = 655
try:
    os.kill(pid, signal.SIGKILL)
    print(f"Successfully killed process {pid}")
except ProcessLookupError:
    print(f"Process {pid} not found")
except PermissionError:
    print(f"Permission denied to kill process {pid}")
except Exception as e:
    print(f"Error: {e}")