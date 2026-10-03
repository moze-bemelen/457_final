```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> MATCHMAKING : Server initialized
    MATCHMAKING --> GAME_BEGIN : Two players joined; server begins game

    CLIENT1 --> GAME_BEGIN : Player 1 connects
    CLIENT2 --> GAME_BEGIN : Player 2 connects

    GAME_BEGIN --> GAMEPLAY : Broadcast initial game state and set first turn

    state "Gameplay cycle" as GAMEPLAY {
        [*] --> PLAYER_TURN
        PLAYER_TURN --> PLACE : Player places on the game board
        PLACE --> EVALUATE_PLACEMENT : Server evaluates placement

        state EVALUATE_PLACEMENT <<choice>>
        EVALUATE_PLACEMENT --> ERROR : Illegal move
        ERROR --> PLAYER_TURN : Send error to client
        EVALUATE_PLACEMENT --> STATE_UPDATE : Valid move
        STATE_UPDATE --> PLAYER_TURN : Record placement, broadcast state, set next turn
        EVALUATE_PLACEMENT --> [*] : Game over
    }

    GAMEPLAY --> GAME_RESULT : Broadcast win, loss, or draw
    GAME_RESULT --> MATCHMAKING : Return to an empty lobby

    state "Client disconnected" as CLIENT_DISCONNECTED
    GAMEPLAY --> CLIENT_DISCONNECTED : Client disconnects unexpectedly
    GAME_BEGIN --> CLIENT_DISCONNECTED : Client disconnects before play begins
    CLIENT_DISCONNECTED --> GAME_RESULT : Forfeit disconnected player and notify remaining player
    CLIENT_DISCONNECTED --> MATCHMAKING : Both clients disconnected; clear game

    MATCHMAKING --> [*] : Server closes
