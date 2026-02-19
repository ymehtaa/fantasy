import json
import os

# Files
MEMBERS_FILE = '../data/league_members.json'
ROSTERS_FILE = '../data/league_rosters.json'
TRANSACTIONS_DIR = '../data/transactions/'
OUTPUT_DIR = '../results/'
STATS_FILE = os.path.join(OUTPUT_DIR, 'activity_vs_performance.json')

os.makedirs(OUTPUT_DIR, exist_ok=True)

def analyze_league():
    # 1. Load data
    with open(MEMBERS_FILE, 'r') as f:
        members = json.load(f)
    with open(ROSTERS_FILE, 'r') as f:
        rosters = json.load(f)

    user_to_name = {m['user_id']: m['display_name'] for m in members}

    # 2. Map Rosters & Calculate Records
    roster_info = {}
    for r in rosters:
        rid = r['roster_id']
        name = user_to_name.get(r['owner_id'], f"Team {rid}")
        
        # Parse the record string (e.g., "WWWLL...")
        record_str = r.get('metadata', {}).get('record', "")
        wins = record_str.count('W')
        losses = record_str.count('L')
        
        roster_info[rid] = {
            "name": name,
            "wins": wins,
            "losses": losses,
            "win_pct": round((wins / (wins + losses)) * 100, 1) if (wins + losses) > 0 else 0,
            "moves": 0
        }

    # 3. Count Transactions for each roster across all weeks
    for week in range(1, 19):
        filename = f"wk{week:02d}_moves.json"
        path = os.path.join(TRANSACTIONS_DIR, filename)
        if not os.path.exists(path): 
            continue

        with open(path, 'r') as f:
            transactions = json.load(f)

        for tx in transactions:
            # We only count completed moves
            if tx.get("status") == "complete":
                for rid in tx.get("roster_ids", []):
                    if rid in roster_info:
                        roster_info[rid]["moves"] += 1

    # 4. Sort by Moves (Descending)
    sorted_comparison = sorted(roster_info.values(), key=lambda x: x['moves'], reverse=True)

    # 5. Print Leaderboard
    print(f"\n{'MANAGER':<15} | {'MOVES':<6} | {'RECORD':<8} | {'WIN %'}")
    print("-" * 50)
    for entry in sorted_comparison:
        record = f"{entry['wins']}-{entry['losses']}"
        print(f"{entry['name'][:15]:<15} | {entry['moves']:<6} | {record:<8} | {entry['win_pct']}%")

    # 6. Save the raw JSON data
    with open(STATS_FILE, 'w') as f:
        json.dump(sorted_comparison, f, indent=2)
    
    print(f"\nRaw statistics saved to: {STATS_FILE}")

if __name__ == "__main__":
    analyze_league()