import json
import os

# This sscript 

PLAYERS_FILE = '../data/players.json'
INPUT_DIR = '../data/transactions/'
OUTPUT_DIR = '../results/'
STATS_FILE = os.path.join(OUTPUT_DIR, 'player_stats.json')

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. Load players db
with open(PLAYERS_FILE, 'r') as f:
    players_db = json.load(f)

player_stats = {}

def get_player_names_and_update_stats(player_ids_dict, action):
    if not player_ids_dict:
        return []
    
    names = []
    for pid_raw in player_ids_dict.keys():
        pid = str(pid_raw)
        player_info = players_db.get(pid, {})
        name = player_info.get('full_name', f"Unknown ({pid})")
        names.append(name)

        if pid not in player_stats:
            player_stats[pid] = {
                "full_name": name,
                "total_transactions": 0,
                "num_added": 0,
                "num_dropped": 0
            }
        
        player_stats[pid]["total_transactions"] += 1
        if action == "add":
            player_stats[pid]["num_added"] += 1
        elif action == "drop":
            player_stats[pid]["num_dropped"] += 1
            
    return names

# 2. Process each weekly file (Handling 01, 02... format)
for week in range(1, 19):
    # The :02d format turns 1 into "01", 2 into "02", but 10 stays "10"
    filename = f"wk{week:02d}_moves.json"
    input_path = os.path.join(INPUT_DIR, filename)
    output_path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(input_path):
        print(f"Skipping {filename}: Not found.")
        continue

    print(f"Processing {filename}...")

    with open(input_path, 'r') as f:
        transactions = json.load(f)

    cleaned_transactions = []

    for tx in transactions:
        is_complete = tx.get("status") == "complete"
        
        adds_raw = tx.get("adds") or {}
        if is_complete:
            add_names = get_player_names_and_update_stats(adds_raw, "add")
        else:
            add_names = [players_db.get(str(p), {}).get('full_name', f"Unknown ({p})") for p in adds_raw]

        drops_raw = tx.get("drops") or {}
        if is_complete:
            drop_names = get_player_names_and_update_stats(drops_raw, "drop")
        else:
            drop_names = [players_db.get(str(p), {}).get('full_name', f"Unknown ({p})") for p in drops_raw]

        cleaned_transactions.append({
            "status": tx.get("status"),
            "type": tx.get("type"),
            "adds_names": add_names,
            "drops_names": drop_names,
            "roster_ids": tx.get("roster_ids")
        })

    with open(output_path, 'w') as f:
        json.dump(cleaned_transactions, f, indent=2)

# 3. Save the stats file
with open(STATS_FILE, 'w') as f:
    json.dump(player_stats, f, indent=2)

print(f"\nSuccess! Processed through {filename}.")