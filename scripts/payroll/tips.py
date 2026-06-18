import os
import json
from collections import defaultdict
from datetime import datetime
from tqdm import tqdm

def get_folders(base_folder):
    """Get all folder names sorted in chronological order."""
    return sorted(
        [f for f in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, f))],
        key=lambda x: datetime.strptime(x, "%b-%d-%Y")
    )

def get_ticket_numbers(folder_path):
    """Extracts Ticket Numbers per Store_ID from Sales_Ticket.txt."""
    ticket_store_map = defaultdict(set)
    sales_ticket_file = os.path.join(folder_path, 'Sales_Ticket.txt')

    if os.path.exists(sales_ticket_file):
        with open(sales_ticket_file, 'r', encoding='utf-8') as file:
            headers = file.readline().strip().split('|')
            if "Ticket_Number" in headers and "Store_ID" in headers:
                ticket_idx = headers.index("Ticket_Number")
                store_idx = headers.index("Store_ID")

                for line in file:
                    values = line.strip().split('|')
                    if len(values) > max(ticket_idx, store_idx):
                        store_id = values[store_idx].strip()
                        ticket_number = values[ticket_idx].strip()
                        ticket_store_map[store_id].add(ticket_number)

    return ticket_store_map

def get_tips(folder_path, ticket_store_map):
    """Matches tickets from Payment.txt and sums Tip_Amount for each store."""
    tip_store_map = defaultdict(float)
    payment_file = os.path.join(folder_path, 'Payment.txt')

    if os.path.exists(payment_file):
        with open(payment_file, 'r', encoding='utf-8') as file:
            headers = file.readline().strip().split('|')
            if "Ticket_Number" in headers and "Tip_Amount" in headers:
                ticket_idx = headers.index("Ticket_Number")
                tip_idx = headers.index("Tip_Amount")
                tip_paid_ix = headers.index("Tip_Paid")

                for line in file:
                    values = line.strip().split('|')
                    if len(values) > max(ticket_idx, tip_idx, tip_paid_ix):
                        ticket_number = values[ticket_idx].strip()
                        tip_amount = float(values[tip_idx]) if values[tip_idx] else 0.0
                        tip_paid = values[tip_paid_ix].strip().lower() == 'true'
                        
                        if tip_paid:
                            for store_id, tickets in ticket_store_map.items():
                                if ticket_number in tickets:
                                    tip_store_map[store_id] += tip_amount

    return tip_store_map

def get_payins(folder_path, tip_store_map):
    """Checks Store_Transactions.txt for Payins and adds Amount to total tips."""
    store_transactions_file = os.path.join(folder_path, 'Store_Transactions.txt')

    if os.path.exists(store_transactions_file):
        with open(store_transactions_file, 'r', encoding='utf-8') as file:
            headers = file.readline().strip().split('|')
            if "Store_ID" in headers and "Transaction_Type_Name" in headers and "Amount" in headers and "Status" in headers:
                store_idx = headers.index("Store_ID")
                type_idx = headers.index("Transaction_Type_Name")
                amount_idx = headers.index("Amount")
                status_idx = headers.index("Status")

                for line in file:
                    values = line.strip().split('|')
                    if len(values) > max(store_idx, type_idx, amount_idx, status_idx):
                        store_id = values[store_idx].strip()
                        transaction_type = values[type_idx].strip()
                        amount = float(values[amount_idx]) if values[amount_idx] else 0.0
                        status = values[status_idx].strip()

                        if transaction_type == "Payins" and status == "Inserted":
                            tip_store_map[store_id] += amount

def get_store_mapping(folder_path, store_mapping):
    """Updates Store_ID to Store_Number mapping from Store.txt."""
    store_file = os.path.join(folder_path, 'Store.txt')

    if os.path.exists(store_file):
        with open(store_file, 'r', encoding='utf-8') as file:
            headers = file.readline().strip().split('|')
            if "Store_ID" in headers and "Store_Number" in headers:
                store_id_idx = headers.index("Store_ID")
                store_number_idx = headers.index("Store_Number")

                for line in file:
                    values = line.strip().split('|')
                    if len(values) > max(store_id_idx, store_number_idx):
                        store_id = values[store_id_idx].strip()
                        store_number = values[store_number_idx].strip()
                        store_mapping[store_id] = store_number

def process_folders(base_folder):
    """Iterates through all folders and calculates total tips per store per day."""
    folders = get_folders(base_folder)
    final_data = {}
    store_mapping = {}  # Store_ID to Store_Number mapping

    for folder_name in tqdm(folders, desc="Processing Days"):
        folder_path = os.path.join(base_folder, folder_name)
        date_str = folder_name  # Use folder name as date

        # Update store mapping from Store.txt
        get_store_mapping(folder_path, store_mapping)

        # Get tips
        ticket_store_map = get_ticket_numbers(folder_path)
        tip_store_map = get_tips(folder_path, ticket_store_map)
        get_payins(folder_path, tip_store_map)

        # Store results using Store_Number instead of Store_ID
        for store_id, total_tip in tip_store_map.items():
            store_number = store_mapping.get(store_id, f"Unknown-{store_id}")

            if store_number not in final_data:
                final_data[store_number] = {"total": 0.0}

            final_data[store_number][date_str] = total_tip
            final_data[store_number]["total"] += total_tip
        
    # Sort final data numerically by Store_Number
    sorted_final_data = dict(sorted(final_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]))

    # Save final output
    with open("tips_summary.json", "w", encoding="utf-8") as json_file:
        json.dump(sorted_final_data, json_file, indent=4)

    print("Tip collection completed and saved to tips_summary.json.")

# Run the process
if __name__ == "__main__":
    base_folder = "Data"
    process_folders(base_folder)
