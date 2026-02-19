import json
from pathlib import Path
from collections import defaultdict

def process_draft_picks():
    # Define paths relative to the script location
    base_path = Path(__file__).parent.parent
    input_path = base_path / "data" / "draft_picks.json"
    output_path = base_path / "data" / "trimmed_picks.json"

    # Load the raw data
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    trimmed_data = []
    # Dictionary to track how many players of each position have been picked
    position_counts = defaultdict(int)

    for pick in data:
        metadata = pick.get("metadata", {})
        pos = metadata.get("position", "Unknown")
        
        # Increment the counter for this specific position
        position_counts[pos] += 1
        
        # Construct the trimmed entry
        entry = {
            "full_name": f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip(),
            "player_id": pick.get("player_id"),
            "position": pos,
            "pick_no": pick.get("pick_no"),
            "pick_no_by_position": position_counts[pos]
        }
        trimmed_data.append(entry)

    # Save the new version
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(trimmed_data, f, indent=2)
    
    print(f"Success! Processed {len(trimmed_data)} picks. Saved to {output_path}")

if __name__ == "__main__":
    process_draft_picks()