import json
import os

# Configuration
MEMBERS_FILE = '../data/league_members.json'
ROSTERS_FILE = '../data/league_rosters.json'
TRANSACTIONS_DIR = '../data/transactions/'
OUTPUT_FILE = '../results/team_waiver_summary.json'

def calculate_team_moves():
    # 1. Load Members and Rosters
    with open(MEMBERS_FILE, 'r') as f:
        members = json.load(f)
    with open(ROSTERS_FILE, 'r') as f:
        rosters = json.load(f)

    # 2. Map owner_id -> display_name
    user_to_name = {m['user_id']: m['display_name'] for m in members}

    # 3. Map roster_id -> display_name
    # We use rosters.json to bridge the gap between ID and Name
    roster_to_name = {}
    for r in rosters:
        rid = r['roster_id']
        owner_id = r['owner_id']
        roster_to_name[rid] = user_to_name.get(owner_id, f"Unknown Team {rid}")

    # 4. Initialize move counters
    # Structure: { "Team Name": {"total": 0, "waiver": 0, "free_agent": 0} }
    stats = {name: {"total": 0, "waiver": 0, "free_agent": 0} for name in roster_to_name.values()}

    # 5. Process all 18 weeks
    for week in range(1, 19):
        filename = f"wk{week:02d}_moves.json"
        path = os.path.join(TRANSACTIONS_DIR, filename)
        
        if not os.path.exists(path):
            continue

        with open(path, 'r') as f:
            transactions = json.load(f)

        for tx in transactions:
            # We only count completed moves
            if tx.get("status") != "complete":
                continue
            
            # Identify the type of move
            tx_type = tx.get("type") # 'waiver' or 'free_agent'
            
            # Transactions can technically involve multiple rosters (trades), 
            # so we loop through roster_ids
            for rid in tx.get("roster_ids", []):
                team_name = roster_to_name.get(rid)
                if team_name and team_name in stats:
                    stats[team_name]["total"] += 1
                    if tx_type in stats[team_name]:
                        stats[team_name][tx_type] += 1

    # 6. Sort by total moves and Save
    sorted_stats = dict(sorted(stats.items(), key=lambda x: x[1]['total'], reverse=True))

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(sorted_stats, f, indent=2)

    # Print a quick leaderboard
    print(f"{'TEAM NAME':<20} | {'TOTAL':<6} | {'WAIVERS':<8} | {'FA'}")
    print("-" * 50)
    for team, data in sorted_stats.items():
        print(f"{team[:20]:<20} | {data['total']:<6} | {data['waiver']:<8} | {data['free_agent']}")

if __name__ == "__main__":
    calculate_team_moves()