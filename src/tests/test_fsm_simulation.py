"""FSM / session simulation with fake connections (no sockets): board fixes, action-name coverage, win, single broadcast,
scores, rematch, forfeit, post-result drop, illegal-message handling.

Run: python3 src/tests/test_fsm_simulation.py
"""
import os, sys
# src/ is the parent of this tests/ folder; optional argv[1] overrides it
SRC = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)
for m in ["board","framing","protocol","fsm","connection","session","server","client"]:
    __import__(m)
print("all 8 modules import")

import board as b
g=b.create_board(); assert not b.is_full(g)
for c in range(7):
    for r in range(6): g[r][c]="X" if (c//2+r)%2 else "O"
assert b.is_full(g)
g=b.create_board()
for _ in range(4): b.drop_disc(g,6,"X")
assert b.check_winner(g)=="X", "vertical col 6"
g=b.create_board()
for r,c in [(2,6),(3,5),(4,4),(5,3)]: g[r][c]="O"
assert b.check_winner(g)=="O", "down-left from col 6"
print("board fixes OK")

import fsm, server, session
names=set(server.Server._build_actions(server.Server.__new__(server.Server)).keys()) | set(session.GameSession(players=[None,None]).actions())
missing={a for _,a in fsm.TRANSITIONS.values() if a and a not in names}
assert not missing, missing
print("every FSM action name resolves")

from fsm import Event, State
from protocol import *
class FakeConn:
    def __init__(s,n): s.player_id=None; s.closed=False; s.close_after_flush=False; s.out=[]; s.addr=n; s.sock=n
    def close(s): s.closed=True
def fake_validate(m): return m
server.validate_incoming=fake_validate
class FakeSel:
    def modify(*a,**k): pass
    def unregister(*a): pass
def mk():
    S=server.Server.__new__(server.Server)
    S.__init__("h",0); S.sel=FakeSel()
    S.open_listener=lambda **d:None
    S.fsm.actions=S._build_actions()
    S._send=lambda c,m: c.out.append(m)
    S._fire(Event.SERVER_READY)
    a,c=FakeConn("a"),FakeConn("b")
    S._dispatch(a,{"msg_type":CONNECT,"player_id":"A"})
    S._dispatch(c,{"msg_type":CONNECT,"player_id":"B"})
    return S,a,c
S,a,c=mk()
assert S.fsm.state is State.PLAYER_TURN and a.out[-1]["msg_type"]==YOUR_TURN
S._dispatch(c,{"msg_type":MOVE,"col":0}); assert c.out[-1]["code"]==OUT_OF_TURN and S.fsm.state is State.PLAYER_TURN
# third client during game is held, not an FSM crash
d=FakeConn("d"); S._dispatch(d,{"msg_type":CONNECT,"player_id":"D"}); assert d in S.waiting
for i in range(3):
    S._dispatch(a,{"msg_type":MOVE,"col":0}); S._dispatch(c,{"msg_type":MOVE,"col":1})
n=len(c.out); S._dispatch(a,{"msg_type":MOVE,"col":0})
assert S.fsm.state is State.GAME_RESULT
res=[m for m in c.out[n:] if m["msg_type"]==RESULT]; assert len(res)==1 and res[0]["winner"]=="A" and res[0]["scores"]["A"]==1
assert not any(m["msg_type"]==STATE for m in c.out[n:]), "only one end broadcast"
states=[m for m in c.out if m["msg_type"]==STATE]; assert len(states)==6, f"one STATE per non-final move, got {len(states)}"
# drop after result must not become forfeit
S._dispatch(a,{"msg_type":REMATCH,"accept":True}); S._dispatch(c,{"msg_type":REMATCH,"accept":True})
assert S.fsm.state is State.PLAYER_TURN and S.session.turn==1 and S.session.wins==[1,0]
print("win, single broadcast, scores, rematch OK")
S._drop(a)
assert any(m["msg_type"]==RESULT and m["outcome"]==FORFEIT and m["winner"]=="B" for m in c.out)
assert c.close_after_flush and S.session is None and S.fsm.state is State.MATCHMAKING
print("mid-game drop -> forfeit -> CLOSE -> MATCHMAKING OK (held client D waiting:", d in S.waiting, ")")
S,a,c=mk()
for i in range(3):
    S._dispatch(a,{"msg_type":MOVE,"col":0}); S._dispatch(c,{"msg_type":MOVE,"col":1})
S._dispatch(a,{"msg_type":MOVE,"col":0})
S._drop(a)
assert S.session is None and S.fsm.state is State.MATCHMAKING
assert not any(m["msg_type"]==RESULT and m["outcome"]==FORFEIT for m in c.out)
print("drop after GAME_RESULT keeps real result OK")
S,a,c=mk(); S._dispatch(a,{"msg_type":REMATCH,"accept":True}); assert a.out[-1]["code"]==UNEXPECTED_MESSAGE
print("illegal message -> ERROR, no crash OK")
