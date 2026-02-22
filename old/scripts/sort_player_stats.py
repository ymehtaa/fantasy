import json
import os

INPUT_FILE = '../results/player_stats.json'
OUTPUT_FILE = '../results/player_stats_sorted.json'

def sort_stats():
    # 1. Check if the file exists
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found. Run the main processing script first!")
        return

    # 2. Load the data
    with open(INPUT_FILE, 'r') as f:
        data = json.load(f)

    # 3. Sort the dictionary
    # We turn the dict items into a list of tuples, then sort by the 
    # nested 'total_transactions' key inside the second element of the tuple.
    sorted_data = dict(sorted(
        data.items(), 
        key=lambda item: item[1]['total_transactions'], 
        reverse=True
    ))

    # 4. Save the sorted data
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(sorted_data, f, indent=2)

    # 5. Print a quick summary of the top 5
    print("--- Most Transacted Players ---")
    for i, (pid, stats) in enumerate(list(sorted_data.items())[:5]):
        print(f"{i+1}. {stats['full_name']} ({stats['total_transactions']} moves)")
    
    print(f"\nFull sorted list saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    sort_stats()