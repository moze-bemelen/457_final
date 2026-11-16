"""Unit tests for framing.py and protocol.py: round-trip, split/coalesced frames, oversize length, every validation error code.

Run: python3 src/tests/test_unit_framing_protocol.py
"""
import os, sys
# src/ is the parent of this tests/ folder; optional argv[1] overrides it
SRC = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)
from framing import *
from protocol import *
m={"msg_type":"MOVE","col":3}
f=encode_message(m); assert f[:4]==len(f[4:]).to_bytes(4,"big") and b" " not in f[4:]
d=FrameDecoder(); out=[]
for b in f: out+=d.feed(bytes([b]))
assert out==[m] and not d.buf, "byte-by-byte"
assert FrameDecoder().feed(f+f+f)==[m,m,m], "coalesced"
d=FrameDecoder(); assert d.feed(f[:4])==[] and d.feed(f[4:])==[m], "header split"
try: FrameDecoder().feed((MAX_MESSAGE_SIZE+1).to_bytes(4,"big")); raise SystemExit("no oversize error")
except FramingError: pass
bad=FrameDecoder().feed((5).to_bytes(4,"big")+b"{oops")[0]; assert DECODE_ERROR_KEY in bad
print("framing OK")
def code(x):
    try: validate_incoming(x); return None
    except ProtocolError as e: return e.code
assert code(bad)==BAD_PAYLOAD and code({})==BAD_PAYLOAD and code({"msg_type":"NOPE"})==UNKNOWN_TYPE
assert code({"msg_type":"CONNECT"})==BAD_PAYLOAD and code({"msg_type":"CONNECT","player_id":"  "})==BAD_PAYLOAD
assert code({"msg_type":"CONNECT","player_id":"x"*33})==BAD_PAYLOAD and code({"msg_type":"CONNECT","player_id":"A"}) is None
assert code({"msg_type":"MOVE","col":True})==BAD_PAYLOAD and code({"msg_type":"MOVE","col":"3"})==BAD_PAYLOAD
assert code({"msg_type":"MOVE","col":7})==COLUMN_RANGE and code({"msg_type":"MOVE","col":-1})==COLUMN_RANGE
assert validate_incoming({"msg_type":"MOVE","payload":{"row":0,"col":2}})["col"]==2
assert code({"msg_type":"REMATCH","accept":1})==BAD_PAYLOAD and code({"msg_type":"REMATCH","accept":False}) is None
print("protocol OK")
