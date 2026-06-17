"""Restart GSV dual-port with log capture to tmp/gsv_*.log.

Usage: PYTHONUTF8=1 uv run python tests/a2d_gsv_restart.py
"""
import subprocess, sys, time, os

GSV_DIR = r"D:\aaa-new\setups\a2d-studio\ref\third_party\GPT-SoVITS-v2pro-20250604"
LOG_DIR = r"D:\aaa-new\setups\a2d-studio\ref\LingChat\tmp"
RUNTIME = os.path.join(GSV_DIR, "runtime", "python.exe")
API_SCRIPT = os.path.join(GSV_DIR, "api_v2.py")
CONFIG = os.path.join(GSV_DIR, "GPT_SoVITS", "configs", "tts_infer.yaml")

os.makedirs(LOG_DIR, exist_ok=True)

# ── Kill existing GSV processes ──
for port in [31801, 31802]:
    try:
        result = subprocess.run(
            ["cmd", "/c", f"netstat -ano | findstr 127.0.0.1:{port}"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5 and "LISTENING" in line:
                pid = parts[-1]
                subprocess.run(["taskkill", "/PID", pid, "/F"],
                               capture_output=True, timeout=5)
                print(f"Killed existing GSV on port {port} (PID {pid})")
    except Exception as e:
        print(f"Warning: could not kill process on port {port}: {e}")

procs = {}

for port in [31801, 31802]:
    log_path = os.path.join(LOG_DIR, f"gsv_{port}.log")
    log_f = open(log_path, "w", encoding="utf-8", errors="replace")

    env = os.environ.copy()
    env["PATH"] = os.path.join(GSV_DIR, "runtime") + ";" + env.get("PATH", "")

    print(f"Starting GSV port {port} → {log_path} ...")
    proc = subprocess.Popen(
        [RUNTIME, API_SCRIPT, "-a", "127.0.0.1", "-p", str(port), "-c", CONFIG],
        stdout=log_f,
        stderr=subprocess.STDOUT,
        cwd=GSV_DIR,
        env=env,
    )
    procs[port] = proc
    print(f"  PID: {proc.pid}")

# Wait for both to be ready
for port, wait in [(31801, 45), (31802, 35)]:
    print(f"Waiting {wait}s for port {port}...")
    for _ in range(wait):
        time.sleep(1)
        try:
            import socket
            s = socket.socket()
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            s.close()
            print(f"  Port {port} is READY")
            break
        except:
            pass
    else:
        print(f"  WARNING: Port {port} may not be ready yet")

print(f"\nGSV restart complete. Logs at:")
for port in [31801, 31802]:
    print(f"  {LOG_DIR}\\gsv_{port}.log")

print(f"\nPIDs: { {p: procs[p].pid for p in procs} }")
print("To stop: taskkill //PID <pid> //F")
