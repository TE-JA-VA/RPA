import io, os, sys, tempfile, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ["RPA_STATUS_DIR"] = tempfile.mkdtemp(prefix="rpa_unlock_")
sys.path.insert(0, r"D:\AX\RPA")
import rpa_dashboard as d
class Fake:
    def __init__(self): self.code = None
    def poll(self): return self.code
fake = Fake()
d.subprocess.Popen = lambda *a, **k: fake
d.launch("routine", "manual:admin")
print("alive while running:", d.launch_state() is not None)
fake.code = 1
print("released after exit:", d.launch_state() is None)
print("stderr file:", os.path.exists(os.path.join(os.environ["RPA_STATUS_DIR"], "stderr_routine.txt")))
d.launch("prepare", "manual:admin")
print("relaunch allowed after exit:", d.launch_state()["target"])
