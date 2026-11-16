"""Integration tests: starts a real server.py process on an ephemeral port and drives it with raw TCP test clients.
Covers split/coalesced frames, every error code, win/rematch/decline, forfeits, held 3rd client, oversize frame,
SIGINT shutdown, turn timeout, and rematch timeout. Exits 1 if any check fails.

Run: python3 src/tests/test_integration_sockets.py
"""
import re, socket, subprocess, time, signal, struct, json
import os, sys
# src/ is the parent of this tests/ folder; optional argv[1] overrides it
SRC = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)
from framing import encode_message, FrameDecoder

def start(timeout="60"):
    p = subprocess.Popen([sys.executable, os.path.join(SRC, "server.py"), "--port", "0", "--turn-timeout", timeout],
                         stderr=subprocess.PIPE, text=True)
    line = p.stderr.readline()
    port = int(re.search(r"listening on .*:(\d+)", line).group(1))
    return p, port

class C:
    def __init__(s, port, name=None):
        s.s = socket.create_connection(("127.0.0.1", port)); s.s.settimeout(3); s.d = FrameDecoder(); s.q = []
        if name: s.send({"msg_type": "CONNECT", "player_id": name})
    def send(s, m): s.s.sendall(encode_message(m))
    def get(s, t=None):
        while True:
            for i, m in enumerate(s.q):
                if t is None or m["msg_type"] == t: return s.q.pop(i)
            data = s.s.recv(4096)
            if not data: return None
            s.q += s.d.feed(data)
    def eof(s):
        try:
            while True:
                data = s.s.recv(4096)
                if not data: return True
                s.q += s.d.feed(data)
        except socket.timeout: return False

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: global failed; failed = True
failed = False

# 1. full game, split + coalesced frames, out-of-turn, column-full, bad JSON, rematch, decline
p, port = start()
a, b = C(port, "A"), C(port, "B")
wa, wb = a.get("WELCOME"), b.get("WELCOME")
check("WELCOME colors X/O with scores", wa["color"] == "X" and wb["color"] == "O" and "scores" in wa)
a.get("YOUR_TURN")
b.send({"msg_type": "MOVE", "col": 0}); check("out-of-turn -> OUT_OF_TURN", b.get("ERROR")["code"] == "OUT_OF_TURN")
f = encode_message({"msg_type": "MOVE", "col": 0})
for byte in f: a.s.send(bytes([byte])); time.sleep(0.002)          # byte-by-byte split frame
st = a.get("STATE"); check("split frame applied (disc at bottom of col 0)", st["board"][5][0] == "X")
b.get("YOUR_TURN"); b.s.sendall(struct.pack(">I", 5) + b"{oops")
check("bad JSON -> BAD_PAYLOAD, connection kept", b.get("ERROR")["code"] == "BAD_PAYLOAD")
b.send({"msg_type": "MOVE", "col": 9}); check("col 9 -> COLUMN_RANGE", b.get("ERROR")["code"] == "COLUMN_RANGE")
b.send({"msg_type": "MOVE", "col": 1}); a.get("YOUR_TURN")
# fill col 6 to test COLUMN_FULL later: alternate A:6 B:6 x3
for _ in range(3):
    a.send({"msg_type": "MOVE", "col": 6}); b.get("YOUR_TURN")
    b.send({"msg_type": "MOVE", "col": 6}); a.get("YOUR_TURN")
a.send({"msg_type": "MOVE", "col": 6}); check("full column -> COLUMN_FULL", a.get("ERROR")["code"] == "COLUMN_FULL")
a.get("YOUR_TURN")
# A: col0 x3 more for vertical win; B plays col 2. Send A's two... coalesced: B sends nothing until its turn
a.send({"msg_type": "MOVE", "col": 0}); b.get("YOUR_TURN")
b.s.sendall(encode_message({"msg_type": "MOVE", "col": 2}) + encode_message({"msg_type": "MOVE", "col": 3}))  # coalesced
check("coalesced: 2nd move rejected OUT_OF_TURN", b.get("ERROR")["code"] == "OUT_OF_TURN")
a.get("YOUR_TURN"); a.send({"msg_type": "MOVE", "col": 0}); b.get("YOUR_TURN")
b.send({"msg_type": "MOVE", "col": 2}); a.get("YOUR_TURN"); a.send({"msg_type": "MOVE", "col": 0})
ra, rb = a.get("RESULT"), b.get("RESULT")
check("vertical win -> RESULT WIN A, scores A=1", ra["outcome"] == "WIN" and ra["winner"] == "A" and rb["scores"]["A"] == 1 and ra["rematch"])
a.send({"msg_type": "REMATCH", "accept": True}); b.send({"msg_type": "REMATCH", "accept": True})
wa2 = a.get("WELCOME"); b.get("WELCOME")
check("rematch -> new WELCOME, empty board, scores kept, B moves first",
      all(c == "." for r in wa2["board"] for c in r) and wa2["scores"]["A"] == 1 and b.get("YOUR_TURN") is not None)
# 2. mid-game disconnect -> forfeit
b.s.close()
r = a.get("RESULT"); check("disconnect mid-game -> FORFEIT to A, A=2", r["outcome"] == "FORFEIT" and r["winner"] == "A" and r["scores"]["A"] == 2)
check("remaining player gets CLOSE then EOF", a.get("CLOSE") is not None and a.eof())
# 3. server back in matchmaking: new pair works; third client held during game
c, d = C(port, "C"), C(port, "D"); c.get("WELCOME"); d.get("WELCOME")
e = C(port, "E")
c.get("YOUR_TURN"); c.send({"msg_type": "MOVE", "col": 3}); check("game continues with 3rd client waiting", c.get("STATE") is not None)
# 4. decline rematch -> CLOSE both, and held client E is paired with next arrival
for col_c, col_d in [(0, 1), (0, 1), (0, 1)]:
    d.get("YOUR_TURN"); d.send({"msg_type": "MOVE", "col": col_d}); c.get("YOUR_TURN"); c.send({"msg_type": "MOVE", "col": 3})
# C has col3 x4? first move 3 + 3 more = 4 vertical
rc = c.get("RESULT"); check("second match result WIN C", rc["winner"] == "C")
c.send({"msg_type": "REMATCH", "accept": False})
check("decline -> CLOSE to both", c.get("CLOSE") is not None and d.get("CLOSE") is not None)
f2 = C(port, "F"); check("held client E paired with new F", e.get("WELCOME")["opponent"] == "F")
# 5. oversized frame -> connection dropped -> forfeit to F
e.s.sendall(struct.pack(">I", 10_000_000))
check("oversized length -> sender dropped, F wins by forfeit", f2.get("RESULT")["outcome"] == "FORFEIT")
# 6. SIGINT graceful shutdown sends CLOSE
g, h = C(port, "G"), C(port, "H"); g.get("WELCOME"); h.get("WELCOME")
p.send_signal(signal.SIGINT); p.wait(5)
check("SIGINT -> CLOSE to clients, server exits 0", g.get("CLOSE")["reason"] == "server shutting down" and h.get("CLOSE") is not None and p.returncode == 0)

# 7. turn timeout
p, port = start("1")
a, b = C(port, "A"), C(port, "B"); a.get("YOUR_TURN")
t0 = time.time(); err = a.get("ERROR"); r = b.get("RESULT")
check(f"turn timeout ({time.time()-t0:.1f}s) -> TURN_TIMEOUT to A, B wins by forfeit", err["code"] == "TURN_TIMEOUT" and r["winner"] == "B")
# invalid moves do not extend the clock
c, d = C(port, "C"), C(port, "D"); c.get("YOUR_TURN"); t0 = time.time()
for _ in range(4): c.send({"msg_type": "MOVE", "col": 9}); time.sleep(0.3)
check("ERROR re-prompts do not reset the deadline", d.get("RESULT")["winner"] == "D" and time.time() - t0 < 2.0)
# rematch prompt timeout counts as decline
e_, f_ = C(port, "E"), C(port, "F"); e_.get("YOUR_TURN")
for col in (0, 1, 0, 1, 0, 1):
    (e_ if col == 0 else f_).send({"msg_type": "MOVE", "col": col}); (f_ if col == 0 else e_).get("YOUR_TURN")
e_.send({"msg_type": "MOVE", "col": 0}); e_.get("RESULT"); e_.send({"msg_type": "REMATCH", "accept": True})
check("unanswered rematch -> CLOSE after timeout", e_.get("CLOSE") is not None)
p.send_signal(signal.SIGINT); p.wait(5)
sys.exit(1 if failed else 0)
