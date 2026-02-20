from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn
import asyncio
import random
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os

from game.logic import Game
from game.action import *

import json

app = FastAPI()


GAMES = {} # game_id -> {"game_state": game_state, "websockets": {player_id: websocket}}

class GameIdRequest(BaseModel):
    game_id: int


ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://catanai-frontend.onrender.com,http://127.0.0.1:5173,http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/create")
async def create_game():
    game_id = random.randint(1000, 9999)
    while game_id in GAMES:
        game_id = random.randint(1000, 9999)
    print(f"Creating game {game_id}")
    
    GAMES[game_id] = {"game_state": False, "websockets": {}}
    player_id = 1
    GAMES[game_id]["websockets"][player_id] = None  # Placeholder for WebSocket connection
    return {"game_id": game_id, "player_id": player_id}


@app.post("/join")
async def join_game(req: GameIdRequest):
    game_id = req.game_id
    print(f"Joining game {game_id}")
    if game_id not in GAMES:
        return JSONResponse(status_code=404, content={"message": "Game not found"})
    if len(GAMES[game_id]["websockets"]) >= 4:
        return JSONResponse(status_code=400, content={"message": "Game is full"})
    if GAMES[game_id]["game_state"]:
        return JSONResponse(status_code=400, content={"message": "Game has already started"})

    # check existing player ids and assign the lowest available (1,2,3,4)
    player_id = min(set(range(1, 5)) - set(GAMES[game_id]["websockets"].keys()))
    GAMES[game_id]["websockets"][player_id] = None  # Placeholder for WebSocket connection

    for conn in GAMES[game_id]["websockets"].values():
        if conn:
            await conn.send_json({"status": "player_joined", "player_id": player_id})

    return {"player_id": player_id, "game_id": game_id}


@app.post("/game/{game_id}/start")
async def start_game(req: GameIdRequest):
    game_id = req.game_id
    if game_id not in GAMES:
        return JSONResponse(status_code=404, content={"message": "Game not found"})
    if GAMES[game_id]["game_state"]:
        return JSONResponse(status_code=400, content={"message": "Game has already started"})
    if len(GAMES[game_id]["websockets"]) < 2:
        return JSONResponse(status_code=400, content={"message": "Not enough players to start the game"})
    
    GAMES[game_id]["game_state"] = True
    # create new game class instance here
    GAMES[game_id]["game_instance"] = Game()

    for player_id in GAMES[game_id]["websockets"].keys():
        GAMES[game_id]['game_instance'].add_player(player_id)

    for conn in GAMES[game_id]["websockets"].values():
        if conn:
            await conn.send_json({"game_state": "True"})
    
    # start game
    start_state = GAMES[game_id]['game_instance'].start_game()

    # send initial game state to all players
    for player_id, conn in GAMES[game_id]["websockets"].items():
        if conn:
            await conn.send_json(start_state[player_id])

    return {"message": "Game started"}



@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(ws: WebSocket, game_id: int, player_id: int):
    origin = ws.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        await ws.close(code=1008) 
        return
    
    await ws.accept()

    if game_id not in GAMES or player_id not in GAMES[game_id]["websockets"]:
        await ws.close(code=1008)
        return
    
    GAMES[game_id]["websockets"][player_id] = ws

    await ws.send_json({
        "type": "lobby_state",
        "players": sorted(GAMES[game_id]["websockets"].keys())
    })

    try:
        while not GAMES[game_id]["game_state"]:
            await ws.send_json({"type": "ping"})
            await asyncio.sleep(2)
    
        game_instance = GAMES[game_id]["game_instance"]
        json.dump(game_instance.get_multiplayer_game_state()[player_id], open("player_state.json", "w"), indent=4)

        await ws.send_json(game_instance.get_multiplayer_game_state()[player_id])

        # Main Game Loop
        while True:
            data = await ws.receive_json()
            
            result = game_instance.call_action(player_id, data)
            
            # if result is false the aciton failed, if result is 1,2,3,4 the player has won, else the new game state is returned
            if result is False: 
                await ws.send_json({"status": "action_failed"})
            elif result in [1,2,3,4]: # player_id won
                for conn in GAMES[game_id]["websockets"].values():
                    if conn:
                        await conn.send_json({"status": "game_over", "winner": result})
            else:
                for pid, conn in GAMES[game_id]["websockets"].items():
                    if conn:
                        await conn.send_json(result[pid])
    
    except WebSocketDisconnect:
        print(f"Player {player_id} disconnected from game {game_id}")

        # Remove the websocket connection
        if player_id in GAMES[game_id]["websockets"]:
            GAMES[game_id]["websockets"].pop(player_id, None)

        # if websockets is empty, remove the game
        if not GAMES[game_id]["websockets"]:
            GAMES.pop(game_id, None)
            return

        # Notify remaining players
        for conn in GAMES[game_id]["websockets"].values():
            if conn:
                await conn.send_json({"status": "player_disconnected", "player_id": player_id})

        # Remove from game instance
        if player_id in game_instance.players:
            game_instance.remove_player(player_id)


        # Check if enough players remain
        if len(game_instance.players) < 2:
            GAMES[game_id]["game_state"] = False
            for conn in GAMES[game_id]["websockets"].values():
                if conn:
                    await conn.send_json({
                        "status": "game_over",
                        "message": "Not enough players to continue the game"
                    })



def start_server(host, port):
    uvicorn.run(app, host=host, port=port)