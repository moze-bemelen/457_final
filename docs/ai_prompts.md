## _All AI prompts used in development will be documented here_

### _Considering [provided all four design markdown documents and diagrams]... provide a pipeline of development and file structure to match specifications and requirements of design process.
### RESPONSE:::
Connect 4 Server and Client: Implementation Plan

This plan covers the full system: a single-threaded, selector-driven TCP server that runs a finite state machine (FSM) over length-prefixed JSON messages, plus a matching terminal client. The design goal is a small, testable core where each layer has one job and nothing sends or changes game state except through the FSM.
Architecture overview

The system has four layers, each depending only on the layer below it:
Layer	Modules	Responsibility	Knows about sockets?
Transport	server.py, client.py	Listening socket, selector loop, non-blocking reads and writes	Yes
Framing and protocol	framing.py, protocol.py	Length-prefixed encoding, decoding, message validation	No
Game control	fsm.py, session.py	States, events, transition table, turn and disconnect handling	No
Game logic	board.py	Board creation, disc drop, win and draw detection	No

Keeping the FSM and board free of socket code means you can test all game rules without a network.
Protocol specification
Transport and framing

    TCP provides the byte stream. Connection setup uses the three-way handshake, which the kernel completes before accept() returns a socket. Reliability (retransmission, ordering, checksums) is handled by TCP's sequence numbers, acknowledgments, and checksum field.
    Framing is a 4-byte big-endian unsigned length header followed by a UTF-8 JSON payload. Its purpose is to recover message boundaries from TCP's byte stream, which can coalesce or split messages.
    Compact JSON (no spaces) keeps frames small and matches the length values computed from the encoded bytes.

Message catalogue

Every message contains msg_type and timestamp, following the format in your spec.
Direction	msg_type	Payload fields	Sent when
Client to server	CONNECT	player_id	Immediately after the socket connects
Server to client	WELCOME	color, board, guide	Match starts (GAME_BEGIN)
Server to client	YOUR_TURN	none	Turn passes to this player
Client to server	MOVE	col (0 to 6)	Player chooses a column
Server to clients	STATE	board, next	After each valid move
Server to client	ERROR	code, message	Move rejected or malformed message
Server to clients	RESULT	outcome (WIN, DRAW, FORFEIT), winner	Game ends
Server to client	CLOSE	reason	Session is finishing and the connection will close

Error codes should be fixed strings such as OUT_OF_TURN, COLUMN_FULL, COLUMN_RANGE, BAD_PAYLOAD, and UNKNOWN_TYPE, so the client can react programmatically.
Server implementation
Module responsibilities

    framing.py: encode_message(dict) -> bytes and a FrameDecoder class with a feed(bytes) -> list[dict] method. The decoder keeps a per-connection bytearray, enforces MAX_MESSAGE_SIZE before buffering the payload, and returns only complete frames.
    protocol.py: validates decoded dicts. It checks that msg_type exists and is known, that required fields are present with the right types, and that col is an integer in range. It returns either a normalized event or raises a ProtocolError with an error code.
    board.py: create_board(), drop_disc(board, col, color) -> row | None, check_winner(board) -> color | None, is_full(board). Win detection scans horizontal, vertical, and both diagonal directions from each cell.
    fsm.py: the state enum, event enum, and transition table. transition(event, **data) looks up (state, event), runs the associated action, and then updates the state. An unlisted pair raises IllegalTransition, and the state does not change if the action raises.
    session.py: GameSession holds the board, the two Player objects, the current turn, and the outcome. Its action functions do the actual work for each FSM transition.
    connection.py: Connection wraps one socket. It owns a FrameDecoder, an outbound bytearray, a player_id once known, and a closed flag.
    server.py: argument parsing, the listening socket, the selector loop, and dispatch to the FSM.

Startup pipeline

    Parse arguments with argparse: --port is required, and --host defaults to 127.0.0.1 for local play.
    Create a listening socket with SO_REUSEADDR, bind it, call listen(2), and set it non-blocking.
    Create a selectors.DefaultSelector and register the listener for EVENT_READ with data=None.
    Create the FSM in INIT, fire SERVER_READY, and move to MATCHMAKING.
    Install a SIGINT handler that sets a running flag to False. The handler should not touch sockets directly.

Main loop pipeline

Each pass through the loop should follow this order:

    Call sel.select(timeout=0.5). The timeout keeps the loop responsive to shutdown and turn deadlines.
    For each ready (key, mask):
        If key.data is None, the listener is ready. Call accept(), which sets the new socket non-blocking, creates a Connection, registers it for EVENT_READ, and fires PLAYER_JOINED.
        Otherwise, call service(key, mask).
    Run deadline checks. If the current player's turn has timed out, fire the timeout event.
    If running is False, begin shutdown: send CLOSE to all connections, flush what can be flushed, and close sockets.

Because the loop processes one ready socket at a time and each transition completes before the next event is handled, the single-writer guarantee from your spec holds.
Service pipeline (per ready socket)

    Write first, if writable. If mask & EVENT_WRITE, call flush(), which sends as many bytes as the kernel accepts from the outbound buffer. If the buffer empties, switch the registration back to EVENT_READ only.
    Read, if readable. If mask & EVENT_READ, call recv(4096).
        Empty bytes mean the peer closed the connection. Fire PLAYER_DROPPED for that connection.
        ConnectionResetError and BrokenPipeError are handled the same way.
        Otherwise, pass the bytes to decoder.feed().
    Dispatch each decoded message in order. For each dict:
        Validate it with protocol.py. On failure, send an ERROR to that client and move on.
        Map the valid message to an FSM event, such as CONNECT to PLAYER_JOINED, or MOVE to MOVE_RECEIVED, and call fsm.transition().
        If the FSM rejects the event as illegal for the current state, send an ERROR with code set to OUT_OF_TURN or UNEXPECTED_MESSAGE.
    Queue outbound frames. Any broadcast triggered by the transition is queued on each recipient's outbound buffer and flushed immediately.

FSM transition pipeline (per event)

    Look up (current_state, event). If it is missing, raise IllegalTransition, which the service layer turns into an ERROR message.
    Run the action. Actions may read and modify the session and queue outbound frames, but they must not call send() directly.
    If the action succeeds, set the new state and log (old_state, event, new_state, timestamp).
    If the action raises, leave the state unchanged and send an ERROR to the originating client.

Transition table
Current state	Event	Next state	Action
INIT	SERVER_READY	MATCHMAKING	Mark server open for connections
MATCHMAKING	PLAYER_JOINED	MATCHMAKING	Add connection to the waiting queue
MATCHMAKING	MATCH_FULL	`GAME_BEG**	Pop two players and create GameSession
`GAME_BEG**	SETUP_SENT	PLAYER_TURN	Queue WELCOME to both, first player is X**
PLAYER_TURN	MOVE_RECEIVED	EVALUATE_PLACEMENT	Check sender is current player and column is valid
EVALUATE_PLACEMENT	MOVE_INVALID	ERROR	Queue ERROR to sender
ERROR	ERROR_SENT	PLAYER_TURN	Queue YOUR_TURN to current player again
EVALUATE_PLACEMENT	MOVE_VALID	STATE_UPDATE	Drop disc on board**
STATE_UPDATE	STATE_SENT	PLAYER_TURN	Queue STATE to both, switch turn**
STATE_UPDATE	GAME_OVER	GAME_RESULT	Record outcome, queue RESULT to both
GAME_RESULT	RESULT_SENT	MATCHMAKING	Queue CLOSE, close sockets, discard session
Any gameplay state	PLAYER_DROPPED	CLIENT_DISCONNECTED	Mark that player as gone
GAME_BEGIN	PLAYER_DROPPED	CLIENT_DISCONNECTED	Mark that player as gone, remaining player requeued or closed
CLIENT_DISCONNECTED	FORFEIT_DECIDED	GAME_RESULT	Set winner to remaining player, outcome FORFEIT
CLIENT_DISCONNECTED	`BOTH_DROPP**	MATCHMAKING	Discard session and resources

Two details the diagram leaves open: a player who drops during GAME_BEGIN should not be deleted from matchmaking silently, and a turn timeout should fire PLAYER_DROPPED for the slow player so it follows the forfeit path.
Disconnect pipeline

    Detect the drop through an empty recv(), a reset, a broken pipe, or a timeout.
    Unregister the socket from the selector and close it.
    Fire PLAYER_DROPPED with the affected player.
    In CLIENT_DISCONNECTED, check how many players remain. One remaining player triggers FORFEIT_DECIDED. Zero triggers BOTH_DROPPED.
    On forfeit, the remaining client receives RESULT with outcome set to FORFEIT, then CLOSE.

A disconnected socket must never be selected again, so unregister it before the next select() call.
Outbound buffer pipeline

    queue(conn, msg) appends encode_message(msg) to conn.outbuf and sets the selector registration to EVENT_READ | EVENT_WRITE.
    flush(conn) calls send(conn.outbuf), deletes the accepted bytes, and keeps the rest.
    When outbuf is empty, switch the registration back to EVENT_READ.
    Use a size cap on outbuf as a safety valve. A client that stops reading should be disconnected rather than allowed to exhaust memory.

Client implementation

The client is simpler because it can block on a single socket, but it still needs the same framing.
Client pipeline

    Parse --host, which defaults to 127.0.0.1, and --port, which is required, using argparse. Parse --name for player_id.
    Connect with socket.create_connection, then send CONNECT.
    Start a reader thread that loops on recv(), feeds a FrameDecoder, and puts each message on a queue.Queue. Using a thread keeps the terminal input responsive while waiting for the server.
    The main thread waits on the queue and handles messages:
        WELCOME: store color, print the board and guide.
        YOUR_TURN: print the board, prompt for a column, and validate it is an integer from 0 to 6 before sending.
        STATE: redraw the board.
        ERROR: print the message and prompt again.
        RESULT or CLOSE: print the outcome and exit cleanly.
    Send MOVE frames with sendall, which is acceptable on a blocking client socket.

Client-side validation is a convenience only. The server remains the authority on turn order and column validity.
Testing pl**
Unit tests

    board.py: horizontal, vertical, and both diagonal wins at each board edge, full-board draws, dropping into an empty column, and rejecting a full column.
    framing.py: round-trip encoding. The decoder must handle one frame split byte by byte, several frames in one chunk, a header split from its payload, and an oversized length value.
    protocol.py: each error code, including missing fields, wrong types, unknown msg_type, and out-of-range columns.
    fsm.py: every row in the transition table, plus a test that unlisted pairs raise IllegalTransition and leave the state unchanged.

Integration tests

Run the server on an ephemeral port and drive it with socket-level test clients:

    Full game from MATCHMAKING through GAME_RESULT back to MATCHMAKING.
    Out-of-turn move and column-full move each return ERROR and do not change the board.
    Partial-frame delivery: send a frame in one-byte chunks with short pauses.
    Coalesced delivery: send two moves in a single sendall.
    Each disconnect path: during GAME_BEGIN, mid-turn, after the game ends, and both players leaving.
    Turn timeout forfeits the slow player.
    A slow reader that stops consuming data is disconnected once its outbound buffer exceeds the cap.

Manual testing

Open two terminals, run the server, connect two clients, and play a complete game. Then repeat with Ctrl+C in the middle of a game to confirm graceful shutdown.
Build order and milestones

    Board and FSM core: board.py, fsm.py, and the unit tests for both. No networking yet.
    Framing and protocol: framing.py and protocol.py with their tests.
    Server skeleton: listener, selector loop, accept(), and a single client echoing a CONNECT through WELCOME.
    Two-player match: matchmaking, GAME_BEGIN, turn loop, and STATE broadcasts, tested with socket-level clients.
    Outcomes and disconnects: win and draw results, forfeits, timeouts, and the disconnect pipeline.
    Client: reader thread, input loop, and message handling.
    Hardening: outbound buffer cap, SIGINT shutdown, logging, and the manual end-to-end run.

Decisions to make early

    Turn timeout length: a value such as 60 seconds is reasonable for a terminal game, and it should be a constant so it's easy to change.
    Matchmaking order: first-in, first-out pairing is simplest. Decide whether the first player to connect is always X.
    Rematch behavior: the current FSM returns to MATCHMAKING, so players must reconnect. Adding a REMATCH event would be a clean extension.
    Logging: use the standard logging module at INFO for transitions and DEBUG for raw frames.

