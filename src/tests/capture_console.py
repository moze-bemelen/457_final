"""Console capture driver: runs server.py and two client.py processes, each client in its own pseudo-terminal,
types scripted moves only after each prompt appears, and saves the verbatim console output.

Outputs (in src/tests/capture_output/ unless a directory is given):
  server.txt, alice.txt, bob.txt, server_raw.txt
Then run build_capture_doc.py to regenerate docs/console_capture.md from those files.

Run: python3 src/tests/capture_console.py [output_dir]      (Linux/macOS: needs the pty module)
"""
import os, pty, re, select, signal, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "capture_output")
PY = sys.executable

os.makedirs(OUT, exist_ok=True)
srv_log = open(f"{OUT}/server_raw.txt", "w")
srv = subprocess.Popen([PY, "server.py", "--port", "0"], cwd=SRC, stderr=srv_log)
while True:
    m = re.search(r"listening on \S+:(\d+)", open(f"{OUT}/server_raw.txt").read())
    if m: port = m.group(1); break
    time.sleep(0.05)

def spawn(args):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(SRC); os.execv(PY, [PY, "client.py", *args])
    return {"pid": pid, "fd": fd, "buf": "", "seen": 0}

clients = {}
clients["alice"] = spawn(["-i", "localhost", "-p", port, "--name", "Alice"])
cmd_a = f"$ python3 client.py -i localhost -p {port} --name Alice"
time.sleep(0.5)
clients["bob"] = spawn(["-i", "127.0.0.1", "-p", port, "--name", "Bob"])
cmd_b = f"$ python3 client.py -i 127.0.0.1 -p {port} --name Bob"
script = {
    "alice": [("(q to quit): ", "3"), ("(q to quit): ", "3"), ("(q to quit): ", "3"), ("(q to quit): ", "3"), ("(y/n): ", "n")],
    "bob":   [("(q to quit): ", "9"), ("(q to quit): ", "2"), ("(q to quit): ", "4"), ("(q to quit): ", "2"), ("(y/n): ", "n")],
}
done = set(); deadline = time.time() + 20
while len(done) < 2 and time.time() < deadline:
    fds = {c["fd"]: n for n, c in clients.items() if n not in done}
    r, _, _ = select.select(list(fds), [], [], 0.2)
    for fd in r:
        n = fds[fd]; c = clients[n]
        try: data = os.read(fd, 4096).decode()
        except OSError: data = ""
        if not data: done.add(n); continue
        c["buf"] += data
        while script[n] and script[n][0][0] in c["buf"][c["seen"]:]:
            prompt, reply = script[n].pop(0)
            c["seen"] = c["buf"].index(prompt, c["seen"]) + len(prompt)
            time.sleep(0.4)                       # human-ish pause so the other side settles
            os.write(fd, (reply + "\n").encode())
for c in clients.values():
    os.waitpid(c["pid"], 0)
srv.send_signal(signal.SIGINT)
srv.wait(timeout=5); srv_log.close()
clean = lambda s: s.replace("\r\n", "\n").replace("\r", "")
open(f"{OUT}/server.txt", "w").write(f"$ python3 server.py --port {port}\n" + clean(open(f"{OUT}/server_raw.txt").read()))
open(f"{OUT}/alice.txt", "w").write(cmd_a + "\n" + clean(clients["alice"]["buf"]))
open(f"{OUT}/bob.txt", "w").write(cmd_b + "\n" + clean(clients["bob"]["buf"]))
print("port", port, "server rc", srv.returncode, "unfinished scripts:", {k: v for k, v in script.items() if v})
