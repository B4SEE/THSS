"""Kill every process on port 8000, then start a fresh Django dev server."""
import subprocess
import sys
import time

PORT = 8000


def pids_on_port(port):
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True
    )
    pids = set()
    for line in result.stdout.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    return pids


def kill_pids(pids):
    for pid in pids:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True
        )
        print(f"  killed PID {pid}")


def main():
    print(f"--- Stopping all processes on port {PORT} ---")
    for attempt in range(5):
        pids = pids_on_port(PORT)
        if not pids:
            break
        kill_pids(pids)
        time.sleep(1)

    remaining = pids_on_port(PORT)
    if remaining:
        print(f"WARNING: could not clear port {PORT}, PIDs still running: {remaining}")
        sys.exit(1)

    print(f"Port {PORT} is clear.")
    print("--- Starting Django server ---")
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", "--noreload"],
        cwd=r"D:\BC\CODE",
    )
    print(f"Server started (PID {proc.pid}). Press Ctrl+C to stop.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("Server stopped.")


if __name__ == "__main__":
    main()
