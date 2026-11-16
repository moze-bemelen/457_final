import enum
from enum import auto
from typing import Dict, Tuple, Optional, Callable
import logging
import datetime

log = logging.getLogger(__name__)
#FSM file will state events and states of the finite state machine cycle
#Soley drives the game state does ot perform actions, those are instead supplied by session.py
#FSM pipeline and flow can be observed in the FSM diagram from project design and architecture stages

class State(enum.Enum):
    INIT = auto() #server initializes
    MATCHMAKING = auto() #server is matchmaking client connections
    GAME_BEGIN = auto() #both clients have joined the server intializes gameplay
    PLAYER_TURN = auto() #server sets active player turn
    EVALUATE_PLACEMENT = auto() #server evaluates placement from valid active player
    STATE_UPDATE = auto() #server broadcasts a update to the game board, score, leaderboard, and game state
    GAME_RESULT = auto() #server broadcasts the result of a finished game upon detection
    ERROR = auto() #server transmists a error to a client when the server detects an unauthorized or illegal move
    CLIENT_DISCONNECT = auto() # server reclaims resources after detecting a client disconnect

class Event(enum.Enum):
    SERVER_READY = auto() #server transfers from initialization to matchmaking
    PLAYER_JOINED = auto() #server opens a new socket to accept a connecting client 
    MATCH_FULL = auto() #server observes two conncurrently connnected players and starts game
    SETUP_SENT = auto() #server broadcasts initial game setup to both connected clients
    MOVE_RECEIVED = auto() #server recieves a move payload from a client
    MOVE_VALID = auto() #server identifies the move is A: from active player B: a authorized and legal move
    MOVE_INVALID = auto() #server identifies an error with player move, transmits a error back to offending client
    ERROR_SENT = auto() #pipeline from MOVE_INVALID
    STATE_SENT = auto() #game state sent post valid player move
    GAME_OVER = auto() #server observes game end/win/draw
    RESULT_SENT = auto() #server broadcasts final game results, no rematch -> close session
    REMATCH = auto() #both players accepted "Play again?", keep session and running scores
    PLAYER_DROPPED = auto() #server identifies a unexpected client disconnect
    FORFEIT_DECIDED = auto() #server handles client disconnect by declaring player forfiet and loss
    BOTH_DROPPED = auto() #server  reclaims all resources and returns back to initial state to attempt matchmaking again

class StateTransitionException(Exception):
    pass

#alias used by server.py and the implementation plan
IllegalTransition = StateTransitionException

'''
Current State, Current event
    -> Next State, action description or none
'''
#Allowed state transitions and flows packed into a dictionary for ease in analyzing transitions during gameplay
TRANSITIONS: Dict[Tuple[State, Event], Tuple[State, Optional[str]]] = {
    #Format is as follows
    #   (Current State, Current event): (Next State, action name or None)
    #Action names must match keys in Server._build_actions() or GameSession.actions().
    #Internal follow-up events (MATCH_FULL, SETUP_SENT, MOVE_VALID/INVALID, ERROR_SENT, STATE_SENT,
    #GAME_OVER, FORFEIT_DECIDED, BOTH_DROPPED) are fired by Server._next_event(), never by clients.

     # Startup and matchmaking
    (State.INIT, Event.SERVER_READY):
        (State.MATCHMAKING, "open_listener"),
    (State.MATCHMAKING, Event.PLAYER_JOINED):
        (State.MATCHMAKING, "enqueue_player"),
    (State.MATCHMAKING, Event.MATCH_FULL):
        (State.GAME_BEGIN, "create_session"),

    # Game setup
    (State.GAME_BEGIN, Event.SETUP_SENT):
        (State.PLAYER_TURN, "send_welcome_and_state"),
    (State.GAME_BEGIN, Event.PLAYER_DROPPED):
        (State.CLIENT_DISCONNECT, "mark_player_gone"),

    # Turn loop
    (State.PLAYER_TURN, Event.MOVE_RECEIVED):
        (State.EVALUATE_PLACEMENT, "record_pending_move"),
    (State.PLAYER_TURN, Event.PLAYER_DROPPED):
        (State.CLIENT_DISCONNECT, "mark_player_gone"),

    #placement evaluation
    (State.EVALUATE_PLACEMENT, Event.MOVE_INVALID):
        (State.ERROR, "queue_error"),
    (State.EVALUATE_PLACEMENT, Event.MOVE_VALID):
        (State.STATE_UPDATE, "apply_move"), #board change + win/draw check only, no broadcast here
    (State.EVALUATE_PLACEMENT, Event.PLAYER_DROPPED):
        (State.CLIENT_DISCONNECT, "mark_player_gone"),

    #error states
    (State.ERROR, Event.ERROR_SENT):
        (State.PLAYER_TURN, "queue_your_turn"),
    (State.ERROR, Event.PLAYER_DROPPED):
        (State.CLIENT_DISCONNECT, "mark_player_gone"),

    #state broadcasts (exactly one broadcast per valid move)
    (State.STATE_UPDATE, Event.STATE_SENT):
        (State.PLAYER_TURN, "broadcast_state_and_switch_turn"),
    (State.STATE_UPDATE, Event.GAME_OVER):
        (State.GAME_RESULT, "record_outcome"),
    (State.STATE_UPDATE, Event.PLAYER_DROPPED):
        (State.CLIENT_DISCONNECT, "mark_player_gone"),

    # Game end
    (State.GAME_RESULT, Event.RESULT_SENT):
        (State.MATCHMAKING, "close_and_discard_session"),
    (State.GAME_RESULT, Event.REMATCH):
        (State.GAME_BEGIN, "reset_for_rematch"),
    #result is already final: a drop here must not route through forfeit and overwrite it
    (State.GAME_RESULT, Event.PLAYER_DROPPED):
        (State.MATCHMAKING, "close_and_discard_session"),

    # Disconnect handling
    (State.CLIENT_DISCONNECT, Event.FORFEIT_DECIDED):
        (State.GAME_RESULT, "record_forfeit"),
    (State.CLIENT_DISCONNECT, Event.BOTH_DROPPED):
        (State.MATCHMAKING, "close_and_discard_session"),
}

class FSM:
    def __init__(self, actions: Dict[str, Callable[..., None]]):
        self.state = State.INIT
        self.actions = actions
    
    def transition(self, event: Event, **data) -> State:
        fsm_key = (self.state, event)

        if fsm_key not in TRANSITIONS:
            raise StateTransitionException(
                f"event {event.name} transition from state {self.state.name} is forbidden"
            )

        next_state, action_name = TRANSITIONS[fsm_key]
        previous_state = self.state

        #if action raises an error state is not changed so the FSM stays where it was not allowing half applied transition to leave the game
        if action_name is not None:
            self.actions[action_name](**data)

        #log change and set next state
        self.state = next_state
        log.info(f"{previous_state.name} -- {event.name} --> {next_state.name} at {datetime.datetime.now()}")
        return next_state

        #method to check if a transition is valid
    def can(self, event:Event) -> bool:
        return (self.state, event) in TRANSITIONS