#!/usr/bin/env python3
"""
Automated test runner for GreenX.
Boots xv6 under QEMU, runs energytest and greenstat, reports results.
"""

import os, re, subprocess, sys, time

TIMEOUT = 120  # seconds to wait for each command

class QEMU:
    def __init__(self):
        q = ["make", "qemu"]
        self.proc = subprocess.Popen(
            q, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        self.outbytes = bytearray()

    def cmd(self, c):
        if isinstance(c, str):
            c = c.encode("utf-8")
        self.proc.stdin.write(c)
        self.proc.stdin.flush()

    def read_available(self):
        try:
            import fcntl
            fd = self.proc.stdout.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            while True:
                try:
                    buf = os.read(fd, 4096)
                    if buf:
                        self.outbytes.extend(buf)
                    else:
                        break
                except BlockingIOError:
                    break
            fcntl.fcntl(fd, fcntl.F_SETFL, fl)
        except Exception:
            pass

    def output(self):
        return self.outbytes.decode("utf-8", "replace")

    def wait_for(self, pattern, timeout=TIMEOUT, show_progress=True):
        deadline = time.time() + timeout
        last_len = 0
        while time.time() < deadline:
            time.sleep(0.5)
            self.read_available()
            out = self.output()
            if show_progress and len(out) > last_len:
                new = out[last_len:]
                print(new, end="", flush=True)
                last_len = len(out)
            if re.search(pattern, out):
                return True
        return False

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main():
    print("=" * 60)
    print("GreenX Automated Test Runner")
    print("=" * 60)
    print("Booting xv6-riscv under QEMU...")
    print()

    q = QEMU()

    # Wait for shell prompt
    if not q.wait_for(r'\$\s*$', timeout=60):
        print("\n[ERROR] xv6 did not reach shell prompt in 60s")
        q.stop()
        sys.exit(1)

    print("\n[xv6 booted successfully]\n")
    print("=" * 60)
    print("Running: energytest")
    print("=" * 60)

    q.cmd("energytest\n")

    # Wait until energytest finishes (look for the summary line)
    if not q.wait_for(r'\d+/6 tests passed', timeout=TIMEOUT):
        print("\n[ERROR] energytest did not complete in time")
        q.stop()
        sys.exit(1)

    # Wait for prompt to return
    q.wait_for(r'\$\s*$', timeout=30)

    print("\n\n" + "=" * 60)
    print("Running: greenstat")
    print("=" * 60)

    q.cmd("greenstat\n")

    # Wait for greenstat to print its footer
    if not q.wait_for(r'Total ticks', timeout=30):
        print("\n[ERROR] greenstat did not complete in time")
        q.stop()
        sys.exit(1)

    # Wait for prompt to return
    q.wait_for(r'\$\s*$', timeout=15)
    time.sleep(1)
    q.read_available()
    out = q.output()

    # Parse results
    print("\n\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    m = re.search(r'(\d+)/6 tests passed', out)
    if m:
        n = int(m.group(1))
        print(f"energytest: {n}/6 tests passed")
        if n == 6:
            print("  All tests PASSED")
        else:
            # Show individual results
            for line in out.splitlines():
                if re.search(r'Test \d+:', line):
                    print(f"  {line.strip()}")
    else:
        print("energytest: could not parse results")

    if re.search(r'Total ticks', out):
        print("greenstat:  ran successfully (printed energy table)")
    else:
        print("greenstat:  FAILED or did not complete")

    print("=" * 60)

    q.stop()

    if m and int(m.group(1)) == 6 and re.search(r'Total ticks', out):
        print("OVERALL: PASS - GreenX is working correctly")
        sys.exit(0)
    else:
        print("OVERALL: FAIL - see output above")
        sys.exit(1)


if __name__ == "__main__":
    main()
