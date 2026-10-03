```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> MATCHMAKING : Server initialized
    MATCHMAKING --> GAME_BEGIN : Two players connection, server initializes game

    CLIENT1 --> GAME_BEGIN : Player 1 connects
    CLIENT2 --> GAME_BEGIN : Player 2 connects

    GAME_BEGIN --> GAMEPLAY : Broadcast initial game-state, board, and short usage guide to clients

    state "Active Game" as GAMEPLAY {
        [*] --> PLAYER_TURN
        PLAYER_TURN --> PLACE : Player transmits column choice for placement
        PLACE --> EVALUATE_PLACEMENT : Server evaluates placement validity 

        state EVALUATE_PLACEMENT <<choice>>
        EVALUATE_PLACEMENT --> ERROR : Move Out of Bounds, Unauthorized, etc
        ERROR --> PLAYER_TURN : Transmit error to client
        EVALUATE_PLACEMENT --> STATE_UPDATE : Valid move
        STATE_UPDATE --> PLAYER_TURN : Record player move, broadcast new game state and set next player to move
        EVALUATE_PLACEMENT --> [*] : Game terminated, set winning player or draw
    }

    GAMEPLAY --> GAME_RESULT : Broadcast win, loss, or draw
    GAME_RESULT --> MATCHMAKING : Gracefully end connections and return to matchmaking

    state "Client disconnected" as CLIENT_DISCONNECTED
    GAMEPLAY --> CLIENT_DISCONNECTED : Client disconnects abruptly
    GAME_BEGIN --> CLIENT_DISCONNECTED : Client disconnects before matchmaking concluded
    CLIENT_DISCONNECTED --> GAME_RESULT : Forfeit disconnected player and notify remaining player to gracefully exit
    CLIENT_DISCONNECTED --> MATCHMAKING : Both clients disconnected. reclaim resources and reset

    MATCHMAKING --> [*] : Server closes for connections
