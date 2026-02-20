import random
import json
from game.action import *
from game.board import Board

# Game Logic file
class Game:
    def __init__(self):
        # Main Game State
        self.players = {}
        self.bank = {"wood": 19, "brick": 19, "sheep": 19, "wheat": 19, "ore": 19}
        self.development_cards = ["knight"] * 14 + ["victory_point"] * 5 + ["road_building"] * 2 + ["year_of_plenty"] * 2 + ["monopoly"] * 2
        random.shuffle(self.development_cards)
        self.number = None
        self.board = Board()

        # Inital Placement Phase
        self.initial_placement_order = None
        self.counter = 0
        self.last_vertex_initial_placement = None

        # Forced Actions (These have to be done before any other action can be taken)
        self.pending_discard: dict[int, int] = {}  # player_id -> number of cards to discard 
        self.forced_action: str | None = None  # One of NEXT_ACTION

        self.robber_candidates: list[int] = []
        self.pending_robber_tile: int | None = None

        self.cards_bought_this_turn = {"knight": 0, "victory_point": 0, "road_building": 0, "year_of_plenty": 0, "monopoly": 0}

        self.temp_road_building = False # Used to track if the player is in the middle of placing roads from a road building card

        # Trading
        self.pending_trade: dict | None = None
        self.no_partner: dict[int, dict] = {}

        # Game Log TODO this will be implemented later
        self.game_log: list[dict] = []

    def add_player(self, player_id):
        if player_id not in self.players:
            self.players[player_id] = {
                "hand": {"wood": 0, "brick": 0, "sheep": 0, "wheat": 0, "ore": 0},
                "development_cards": {"knight": 0, "victory_point": 0, "road_building": 0, "year_of_plenty": 0, "monopoly": 0},
                "played_knights": 0,
                "longest_road_length": 0,
                "victory_points": 0,
                "settlements": 5,
                "cities": 4,
                "roads": 15,
                "ports": [],
                "longest_road": False,
                "largest_army": False,
                "played_card_this_turn": False,
                "dice_rolled": False,
                "current_turn": False,
                
                # For public state
                "total_hand": 0,  
                "total_development_cards": 0,
                "victory_points_without_vp_cards": 0  
            }
    
    def remove_player(self, player_id):
        if player_id in self.players:
            del self.players[player_id]

    def start_game(self):
        if len(self.players) < 2 or len(self.players) > 4:
            return False
        current_turn = random.choice(list(self.players.keys()))
        self.players[current_turn]["current_turn"] = True
        order = list(range(1, len(self.players)+1))
        order = order[current_turn-1:] + order[:current_turn-1]
        order += order[::-1]
        self.initial_placement_order = [i for i in order for _ in (range(2))]

        # The initial placement phase is done separately, since it requires player interaction
        self.current_turn = current_turn
        return self.get_multiplayer_game_state()
    

    def initial_placement_phase(self, player_id: int, action: dict) -> dict:
        # check if action is from the correct player
        if player_id != self.initial_placement_order[self.counter]:
                return False
                    
        # check if action is even (settlement) or odd (road)
        if self.counter % 2 == 0: # settlement
            if not action.get("type") == "place_settlement":
                return False
            if not initial_placement_round(board = self.board, vertex_id = int(action.get("vertex_id")), player_id = player_id, players = self.players):
                return False
            
            # check if second round of initial placement
            if self.counter >= len(self.initial_placement_order)//2:
                # give resources for the settlement placed
                for tile in self.board.vertices[int(action.get("vertex_id"))].tiles:
                    resource = self.board.tiles[tile].resource
                    if resource != "Desert":
                        self.players[player_id]["hand"][resource.lower()] += 1
                        self.bank[resource.lower()] -= 1
            
            self.last_vertex_initial_placement = int(action.get("vertex_id"))
        
        else: # road
            if not action.get("type") == "place_road":
                return False
            # check if edge is connected to last placed settlement
            if self.last_vertex_initial_placement is None:
                return False
            connected_edges = self.board.vertices[self.last_vertex_initial_placement].edges
            if int(action.get("edge_id")) not in connected_edges:
                return False
            
            if not initial_placement_round_road(board = self.board, edge_id = int(action.get("edge_id")), player_id = player_id, players = self.players, vertex_id=self.last_vertex_initial_placement):
                return False
            
            self.last_vertex_initial_placement = None
        
        self.counter += 1
        return True
            

    
    def call_action(self, player_id: int, action: dict) -> bool | dict:
        if self.counter < len(self.initial_placement_order): # only allow initial placement actions
            success = self.initial_placement_phase(player_id, action)
        else:
            success = self.process_action(player_id, action)
        
        if not success:
            return False

        # Calculate longest road, as it can change after any action
        for player_id in self.players.keys():
            calculate_longest_road(self.board, player_id, self.players)
        update_longest_road(self.players)
        
        if self.players[player_id]["victory_points"] >= 10:
            return player_id  # player_id won
        
        # return a list of game states for all players
        return self.get_multiplayer_game_state()


    def process_action(self, player_id: int, action: dict) -> bool:
        # Validate turn and phase
        action_type = action.get("type")

        # Out-of-turn actions allowed:
        if action_type == 'accept_trade' or action_type == 'decline_trade':
            pass
        elif self.forced_action == "Discard" and action_type == "discard_resources":
            pass
        elif player_id != self.current_turn:
            return False
        

        # If a forced action is active, restrict what the current player can do.
        if self.forced_action and action_type not in ["discard_resources", "move_robber", "robber_steal", "Year of Plenty", "Monopoly", "place_road", "Trade Pending", "accept_trade", "decline_trade", "confirm_trade", "end_trade"]:
            return False
        if self.pending_trade and player_id == self.current_turn and action_type == "end_turn":
            return False

        
        # Route action (Return False if action is invalid)
        match action_type:
            # General actions
            case "roll_dice":
                self.number = roll_dice(board = self.board, players = self.players, player_id = player_id, bank = self.bank)
                if self.number is False:
                    return False
                
                if self.number == 7:
                    self.pending_discard.clear()
                    for pid, pdata in self.players.items():
                        total_cards = sum(pdata["hand"].values())
                        if total_cards > 7:
                            self.pending_discard[pid] = total_cards // 2
                        
                    if self.pending_discard:
                        self.forced_action = "Discard"
                    else:
                        self.forced_action = "Move Robber"

                return True
            
            case "end_turn":
                if end_turn(player_id = player_id, players = self.players):
                    self.number = None
                    self.current_turn = (self.current_turn % len(self.players)) + 1
                    self.cards_bought_this_turn = {"knight": 0, "victory_point": 0, "road_building": 0, "year_of_plenty": 0, "monopoly": 0}
                    return True
                else:
                    return False
            
            case "discard_resources":
                # Only valid during forced Discard phase and only for players who still owe
                if self.forced_action != "Discard" or player_id not in self.pending_discard or self.pending_discard[player_id] <= 0:
                    return False
                owed = self.pending_discard.get(player_id, 0)
                if owed <= 0:
                    return False

                # Validate discard request
                resources = action.get("resources", {}) or {}
                total_to_remove = sum(int(resources.get(k, 0)) for k in ["wood","brick","sheep","wheat","ore"])
                if total_to_remove != owed:
                    return False

                # Attempt to remove resources
                success = remove_resources(player_id = player_id, players = self.players, resources = resources, bank = self.bank)
                if not success:
                    return False

                # Mark this player's discard as satisfied
                self.pending_discard[player_id] = 0

                # If all finished, advance to robber placement
                if all(v <= 0 for v in self.pending_discard.values()):
                    self.forced_action = "Move Robber"

                return True
            
            case "move_robber":
                # Only current player resolves robber
                if player_id != self.current_turn or self.forced_action != "Move Robber":
                    return False
                
                target_tile = int(action.get("target_tile"))
                # Step 1: placing the robber (always allowed when called)
                if not move_robber(board=self.board, new_tile_id=target_tile):
                    return False

                # Figure out eligible victims at this tile (exclude self)
                cands = robbable_players_on_tile(board = self.board, players= self.players, tile_id=target_tile, current=player_id)
                self.pending_robber_tile = target_tile
                self.robber_candidates = cands
                self.forced_action = "Steal Resource" if cands else None
                return True

            case "robber_steal":
                # Current player must pick among announced candidates
                if self.forced_action != "Steal Resource" or player_id != self.current_turn:
                    return False
                
                victim = int(action.get("victim_id"))
                if victim not in (self.robber_candidates or []):
                    return False
                if not steal_resource(board=self.board, players=self.players, stealer_id=player_id, victim_id=victim):
                    return False
                
                self.robber_candidates = []
                self.pending_robber_tile = None
                self.forced_action = None
                return True

            # Building actions
            case "place_road":
                if self.forced_action in ["Place Road 1", "Place Road 2"] and player_id == self.current_turn:
                    
                    self.temp_road_building = False
                    if self.players[player_id]["dice_rolled"] == False:
                            self.temp_road_building = True
                            self.players[player_id]["dice_rolled"] = True

                    if self.forced_action == "Place Road 1":
                        self.players[player_id]["hand"]["wood"] += 1
                        self.players[player_id]["hand"]["brick"] += 1
                        self.bank["wood"] -= 1
                        self.bank["brick"] -= 1

                        if not place_road(board = self.board, edge_id = int(action.get("edge_id")), player_id = player_id, players = self.players, bank = self.bank):
                            self.players[player_id]["hand"]["wood"] -= 1
                            self.players[player_id]["hand"]["brick"] -= 1
                            self.bank["wood"] += 1
                            self.bank["brick"] += 1

                            if self.temp_road_building:
                                self.players[player_id]["dice_rolled"] = False
                            return False
                        
                        if self.players[player_id]["roads"] <= 0:
                            self.forced_action = None
                        else:
                            self.forced_action = "Place Road 2"
                        
                        if self.temp_road_building:
                            self.players[player_id]["dice_rolled"] = False
                        return True
                    
                    
                    else: # Place Road 2
                        self.players[player_id]["hand"]["wood"] += 1
                        self.players[player_id]["hand"]["brick"] += 1
                        self.bank["wood"] -= 1
                        self.bank["brick"] -= 1
                        
                        if not place_road(board = self.board, edge_id = int(action.get("edge_id")), player_id = player_id, players = self.players, bank = self.bank):
                            self.players[player_id]["hand"]["wood"] -= 1
                            self.players[player_id]["hand"]["brick"] -= 1
                            self.bank["wood"] += 1
                            self.bank["brick"] += 1

                            if self.temp_road_building:
                                self.players[player_id]["dice_rolled"] = False
                            return False

                        if self.temp_road_building:
                            self.players[player_id]["dice_rolled"] = False    
                        self.forced_action = None
                        return True
                else:
                    return place_road(board = self.board, edge_id = int(action.get("edge_id")), player_id = player_id, players = self.players, bank = self.bank)
            
            case "place_settlement":
                return place_settlement(board = self.board, vertex_id = int(action.get("vertex_id")), player_id = player_id, players = self.players, bank = self.bank)
            
            case "place_city":
                return place_city(board = self.board, vertex_id = int(action.get("vertex_id")), player_id = player_id, players = self.players, bank = self.bank)
            
            case "buy_development_card":
                card = buy_development_card(player_id= player_id, development_cards = self.development_cards, players = self.players, bank = self.bank)
                if not card:
                    return False
                self.cards_bought_this_turn[card] += 1
                return True

            # Development Card actions
            case "play_knight_card":
                if not play_knight(player_id = player_id, players = self.players, this_turn_cards = self.cards_bought_this_turn):
                    return False
                
                self.forced_action = "Move Robber"
                return True
                
            case "play_road_building_card":
                if not play_road_building(player_id = player_id, players = self.players, this_turn_cards = self.cards_bought_this_turn):
                    return False
                if self.players[player_id]["roads"] <= 0:
                    return False
                self.forced_action = "Place Road 1"
                return True
    
            case "play_year_of_plenty_card":
                if not play_year_of_plenty(player_id = player_id, players = self.players, this_turn_cards = self.cards_bought_this_turn):
                    return False
                self.forced_action = "Year of Plenty"
                return True
            
            
            case "play_monopoly_card":
                if not play_monopoly(player_id = player_id, players = self.players, this_turn_cards = self.cards_bought_this_turn):
                    return False
                self.forced_action = "Monopoly"
                return True
            
            case "Year of Plenty":
                if self.forced_action != "Year of Plenty" or player_id != self.current_turn:
                    return False
                resources = action.get("resources", []) or []
                if len(resources) != 2 or any(r not in ["wood","brick","sheep","wheat","ore"] for r in resources):
                    return False
                self.players[player_id]["hand"][resources[0]] += 1
                self.players[player_id]["hand"][resources[1]] += 1
                self.bank[resources[0]] -= 1
                self.bank[resources[1]] -= 1
                self.forced_action = None
                return True
                
            case "Monopoly":
                if self.forced_action != "Monopoly" or player_id != self.current_turn:
                    return False
                resource = action.get("resource")
                if resource not in ["wood","brick","sheep","wheat","ore"]:
                    return False
                
                total_collected = 0
                for opponent_id in self.players:
                    if opponent_id != player_id:
                        total_collected += self.players[opponent_id]["hand"][resource]
                        self.players[opponent_id]["hand"][resource] = 0
                
                self.players[player_id]["hand"][resource] += total_collected
                self.forced_action = None
                return True
                

            # Trade actions
            case "bank_trade":
                offer = action.get("offer", {}) or {}
                request = action.get("request", {}) or {}
                if not can_do_trade_bank(player_id=player_id, resource_give=offer, resource_receive=request, players=self.players, bank=self.bank):
                    return False
                return complete_trade_bank(player_id=player_id, resource_give=offer, resource_receive=request, players=self.players, bank=self.bank)

            case "propose_trade":
                if self.pending_trade is not None:
                    return False  # only one active proposal at a time
                offer = action.get("offer", {}) or {}
                request = action.get("request", {}) or {}

                if not trade_possible(player_id=player_id, offer=offer, request=request, players=self.players, bank=self.bank):
                    return False

                recipients = [pid for pid in self.players.keys() if pid != player_id]
                if not recipients:
                    return False

                self.pending_trade = {
                    "trader_id": player_id,
                    "offer": offer,
                    "request": request,
                    "awaiting": set(recipients),
                    "declined": set(),
                    "accepted_by": set(),
                    "target": None
                }
                # keep the current player's flow "locked" until resolved
                self.forced_action = self.forced_action or "Trade Pending"
                return True

            case "accept_trade":
                if self.pending_trade is None:
                    return False

                trader = self.pending_trade["trader_id"]
                offer = self.pending_trade["offer"]
                request = self.pending_trade["request"]
                partner = player_id
                if partner == trader:
                    return False
 
                # must be one of the invited players
                if partner not in self.players:
                    return False
       
            
                # Validate partner can pay request now
                if not can_do_trade_player(partner, request, self.players):
                    return False
   
                self.pending_trade["accepted_by"].add(partner)
                if player_id in self.pending_trade["awaiting"]:
                    self.pending_trade["awaiting"].remove(partner)
                elif player_id in self.pending_trade["declined"]:
                    self.pending_trade["declined"].remove(partner)

                return True

            case "confirm_trade":
                if self.pending_trade is None:
                    return False
                if player_id != self.pending_trade["trader_id"]:
                    return False
                if not self.pending_trade["accepted_by"]:
                    return False
                
                partner = action.get("target")
                if partner not in self.pending_trade["accepted_by"]:
                    return False

                trader = self.pending_trade["trader_id"]
                offer = self.pending_trade["offer"]
                request = self.pending_trade["request"]

                if not complete_trade_player(trader_id=trader, partner_id=partner, offer=offer, request=request, players=self.players):
                    return False
                
                self.pending_trade = None
                if self.forced_action == "Trade Pending":
                    self.forced_action = None
                return True

            case "decline_trade":
                if self.pending_trade is None:
                    return False
                trader = self.pending_trade["trader_id"]
                partner = player_id
                if partner == trader:
                    return False
                # mark response
                if partner in self.pending_trade["awaiting"]:
                    self.pending_trade["awaiting"].remove(partner)
                    self.pending_trade["declined"].add(partner)
                
                elif partner in self.pending_trade["accepted_by"]:
                    self.pending_trade["accepted_by"].remove(partner)
                    self.pending_trade["declined"].add(partner)

                return True
            
            case "end_trade":
                if self.pending_trade is None:
                    return False
                if player_id != self.pending_trade["trader_id"]:
                    return False
                self.pending_trade = None
                if self.forced_action == "Trade Pending":
                    self.forced_action = None
                return True


            case _:
                return False

   
    # Update we always want the full game state for each player (since hidden info) (And send it to everyone)
    def get_multiplayer_game_state(self) -> dict:
        # add total development cards and hand size for all players, so it can be used in public state
        for _, pdata in self.players.items():
            pdata["total_hand"] = sum(pdata["hand"].values())
            pdata["total_development_cards"] = sum(pdata["development_cards"].values())
            pdata["victory_points_without_vp_cards"] = pdata["victory_points"] - pdata["development_cards"]["victory_point"]

        pending_trade_view = None
        if self.pending_trade is not None:
            # serialize sets for JSON
            pending_trade_view = {
                "trader_id": self.pending_trade["trader_id"],
                "offer": self.pending_trade["offer"],
                "request": self.pending_trade["request"],
                "awaiting": sorted(list(self.pending_trade["awaiting"])),
                "declined": sorted(list(self.pending_trade["declined"])),
                "accepted_by": sorted(list(self.pending_trade["accepted_by"])),
                "target": self.pending_trade["target"],
            }

        result = {}
        for player in self.players.keys():
            player_data = {player: self.players[player]}
            public_player_data = self.public_player_state(player)
            players = {**player_data, **public_player_data}
            must_discard = self.pending_discard.get(player, 0) if self.forced_action == "Discard" else 0

            result[player] = {
                "board": self.board.board_to_json(),
                "players": players,
                "bank": self.bank,
                "development_cards_remaining": len(self.development_cards),
                "current_turn": self.current_turn,
                "current_roll": self.number,
                "initial_placement_order": self.initial_placement_order[self.counter] if self.counter < len(self.initial_placement_order) else -1,
                
                # Game flow 
                "forced_action": self.forced_action,
                "must_discard": must_discard,
                "robber_candidates": self.robber_candidates,         # [] or [2,3,...]
                "pending_robber_tile": self.pending_robber_tile,     # int or None

                "pending_trade": pending_trade_view,
                "no_partner": self.no_partner.get(player, {}),
            }
        
        self.no_partner.clear()
        return result


    def public_player_state(self, player_id: int) -> dict:
        # all players except player_id
        player_id_public_state = {}
        for pid, pdata in self.players.items():
            if pid == player_id:
                continue
            player_id_public_state[pid] = {
                "total_hand": pdata["total_hand"],
                "total_development_cards": pdata["total_development_cards"],
                "victory_points_without_vp_cards": pdata["victory_points_without_vp_cards"],

                "played_knights": pdata["played_knights"],
                "longest_road_length": pdata["longest_road_length"],
                "victory_points": pdata["victory_points"] - pdata["development_cards"]["victory_point"],
                "settlements": pdata["settlements"],
                "cities": pdata["cities"],
                "roads": pdata["roads"],
                "ports": pdata["ports"],
                "longest_road": pdata["longest_road"],
                "largest_army": pdata["largest_army"],
                "played_card_this_turn": pdata["played_card_this_turn"],
                "dice_rolled": pdata["dice_rolled"],
                "current_turn": pdata["current_turn"]
            }
        return player_id_public_state
