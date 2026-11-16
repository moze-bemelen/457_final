# Tests and Console Capture Tools

Test suites, drivers, and console-capture tools for the Connect-4 server and client.
All scripts find `src/` on their own, so they can be run from any directory. They use only the
Python standard library. `capture_console.py` needs the `pty` module (Linux/macOS).

The history of how these were built and what each run showed is in `docs/agent_workflow.md`
(Sessions 2–5).

## Quick start

```bash
python3 src/tests/run_all.py          # runs the three test suites, exits 1 on any failure
```

## Files

| File | Type | What it does |
|---|---|---|
| `run_all.py` | runner | Runs the three `test_*.py` scripts and prints a PASS/FAIL summary |
| `test_unit_framing_protocol.py` | unit | `framing.py`: round trip, frame fed byte by byte, several frames in one chunk, header split from payload, oversize length, bad JSON. `protocol.py`: every `validate_incoming` error code, blueprint-form MOVE |
| `test_fsm_simulation.py` | simulation | FSM + session with fake connections and a fake selector (no sockets): board win/full fixes, every FSM action name resolves, win with a single broadcast, scores, rematch, forfeit, drop after a result, illegal-message handling |
| `test_integration_sockets.py` | integration | Starts a real `server.py` on an ephemeral port and drives it with raw TCP clients. 20 checks: split/coalesced frames, all error codes, win/rematch/decline, forfeits, 3rd client held for next match, oversize frame, SIGINT shutdown, turn timeout, rematch timeout |
| `capture_console.py` | driver | Runs the server and two `client.py` processes, each client in its own pseudo-terminal. Types scripted moves only after each prompt appears and saves the verbatim console output to `capture_output/` |
| `build_capture_doc.py` | doc builder | Builds `docs/console_capture.md` from the files in `capture_output/` (inserted unedited) |
| `capture_output/` | data | Captured `server.txt`, `alice.txt`, `bob.txt` from the run shown in `docs/console_capture.md` |

## Regenerating the console capture

```bash
python3 src/tests/capture_console.py      # writes src/tests/capture_output/*.txt
python3 src/tests/build_capture_doc.py    # rewrites docs/console_capture.md
```

The move script lives in `capture_console.py` (Alice plays column 3 four times; Bob types `9`, then
plays 2, 4, 2). The timeline table in `build_capture_doc.py` describes that script, so update both
together if you change the moves.

## Notes

- The integration test and capture driver use `--port 0` (the OS picks a free port) and
  `--turn-timeout 1` for the timeout checks, so they don't collide with a running server.
- Everything runs on loopback (`127.0.0.1`). A capture on the CML topology (clients on Subnets A/B →
  `server.bemelen.edu`) has to be done in the lab.
