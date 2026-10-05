## beckend.py file
import json
import os
import tempfile
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "order.json"

VALID_STATUSES = ("available", "occupied", "reserved", "cleaning")



# Internal helpers

def _ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def _fail(message):
    return {"success": False, "message": message, "data": None}


def _default_data():
    return {"tables": {}}


def _parse_table_number(value):
    """Return (int_table_number, None) or (None, error_response)."""
    if isinstance(value, bool):
        return None, _fail("Table number must be a positive integer.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None, _fail("Table number must be a positive integer.")
    if number <= 0:
        return None, _fail("Table number must be a positive integer.")
    return number, None


def _parse_item(item):
    """Return (clean_item_name, None) or (None, error_response)."""
    if not isinstance(item, str) or not item.strip():
        return None, _fail("Item must be a non-empty string.")
    return item.strip(), None


def _parse_quantity(quantity):
    """Return (quantity, None) or (None, error_response)."""
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return None, _fail("Quantity must be an integer greater than 0.")
    if quantity <= 0:
        return None, _fail("Quantity must be an integer greater than 0.")
    return quantity, None


def _find_item(orders, item):
    """Case-insensitive lookup of an item in a table's order list."""
    wanted = item.strip().lower()
    for entry in orders:
        if entry["item"].strip().lower() == wanted:
            return entry
    return None


def _load_table(table_number):
    """Validate the number and fetch the table.
    Returns (number, data, table, None) or (None, None, None, error_response)."""
    number, err = _parse_table_number(table_number)
    if err:
        return None, None, None, err
    data = load_data()
    table = data["tables"].get(str(number))
    if table is None:
        return None, None, None, _fail(f"Table {number} does not exist.")
    return number, data, table, None


def _snapshot(number, table):
    return {
        "table_number": number,
        "status": table["status"],
        "orders": [dict(o) for o in table["orders"]],
        "notes": table["notes"],
        "phone": table.get("phone", ""),
    }



# Data functions

def load_data():
    """Load restaurant.json. Creates it if missing; recovers safely if the JSON is broken."""
    if not DATA_FILE.exists():
        data = _default_data()
        save_data(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
            raise ValueError("Unexpected structure")
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        # Keep the broken file as a backup instead of destroying it, then start clean.
        try:
            backup = DATA_FILE.with_name(DATA_FILE.name + ".corrupt")
            os.replace(DATA_FILE, backup)
        except OSError:
            pass
        data = _default_data()
        save_data(data)
        return data


def save_data(data):
    """Write the full data dict to restaurant.json (atomic: temp file, then replace)."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, DATA_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise



# Table management

def create_table(table_number):
    number, err = _parse_table_number(table_number)
    if err:
        return err
    data = load_data()
    if str(number) in data["tables"]:
        return _fail(f"Table {number} already exists.")
    data["tables"][str(number)] = {"status": "available", "orders": [], "notes": ""}
    save_data(data)
    return _ok(f"Table {number} created.", _snapshot(number, data["tables"][str(number)]))


def delete_table(table_number):
    number, data, table, err = _load_table(table_number)
    if err:
        return err
    if table["orders"]:
        return _fail(f"Cannot delete Table {number} because it has active orders.")
    del data["tables"][str(number)]
    save_data(data)
    return _ok(f"Table {number} deleted.", {"table_number": number})


def view_table(table_number):
    number, _, table, err = _load_table(table_number)
    if err:
        return err
    return _ok(f"Details for Table {number}.", _snapshot(number, table))


def view_all_tables():
    data = load_data()
    rows = [
        {"table_number": int(k), "status": v["status"]}
        for k, v in sorted(data["tables"].items(), key=lambda kv: int(kv[0]))
    ]
    return _ok(f"{len(rows)} table(s) found.", rows)


# Status helpers

def check_table_status(table_number):
    """Report the status and whether an order can be added right now."""
    number, _, table, err = _load_table(table_number)
    if err:
        return err
    status = table["status"]
    return _ok(
        f"Table {number} is {status}.",
        {
            "table_number": number,
            "stas": status,
            "can_add_order": status in ("available", "occupied"),
            "is_existing_order": status == "occupied",
        },
    )


def is_table_available(table_number):
    number, err = _parse_table_number(table_number)
    if err:
        return False
    table = load_data()["tables"].get(str(number))
    return bool(table) and table["status"] == "available"


def update_table_status(table_number, status):
    if not isinstance(status, str) or status.strip().lower() not in VALID_STATUSES:
        return _fail("Invalid table status.")
    status = status.strip().lower()

    number, data, table, err = _load_table(table_number)
    if err:
        return err

    # A table with live orders has to stay occupied, otherwise orders and status disagree.
    if table["orders"] and status != "occupied":
        return _fail(
            f"Table {number} has active orders. Use clear_table({number}) to end the session first."
        )

    table["status"] = status
    save_data(data)
    return _ok(f"Table {number} status set to {status}.", _snapshot(number, table))



# Order management

def add_order(table_number, item, quantity):
    """Add an item to a table. Always checks the table status first."""
    number, data, table, err = _load_table(table_number)
    if err:
        return err
    item, err = _parse_item(item)
    if err:
        return err
    quantity, err = _parse_quantity(quantity)
    if err:
        return err

    status = table["status"]

    if status == "reserved":
        return _fail(f"Table {number} is reserved and is not available for a new order.")
    if status == "cleaning":
        return _fail(f"Table {number} is currently being cleaned.")

    # available -> starts a new session, occupied -> updates the existing one
    started_session = status == "available"
    if started_session:
        table["status"] = "occupied"

    existing = _find_item(table["orders"], item)
    if existing:
        existing["quantity"] += quantity
    else:
        table["orders"].append({"item": item, "quantity": quantity})

    save_data(data)
    if started_session:
        message = f"New order started on Table {number}: {item} x {quantity}. Table is now occupied."
    elif existing:
        message = f"Updated {existing['item']} on Table {number}. New quantity: {existing['quantity']}."
    else:
        message = f"Added {item} x {quantity} to Table {number}."
    return _ok(message, _snapshot(number, table))


def edit_order(table_number, item, quantity):
    """Set the quantity of an item that is already on the table."""
    number, data, table, err = _load_table(table_number)
    if err:
        return err
    item, err = _parse_item(item)
    if err:
        return err
    quantity, err = _parse_quantity(quantity)
    if err:
        return err

    if table["status"] != "occupied":
        return _fail(f"Table {number} is {table['status']}, so it has no active order to edit.")

    existing = _find_item(table["orders"], item)
    if not existing:
        return _fail(f"{item} is not present in Table {number} orders.")

    old_quantity = existing["quantity"]
    existing["quantity"] = quantity
    save_data(data)
    return _ok(
        f"{existing['item']} on Table {number} changed from {old_quantity} to {quantity}.",
        _snapshot(number, table),
    )


def remove_order(table_number, item):
    """Remove one item. If it was the last one, the table goes back to available."""
    number, data, table, err = _load_table(table_number)
    if err:
        return err
    item, err = _parse_item(item)
    if err:
        return err

    existing = _find_item(table["orders"], item)
    if not existing:
        return _fail(f"{item} is not present in Table {number} orders.")

    table["orders"].remove(existing)
    message = f"Removed {existing['item']} from Table {number}."
    if not table["orders"]:
        table["status"] = "available"
        table["notes"] = ""
        message += f" No orders left, Table {number} is now available."
    save_data(data)
    return _ok(message, _snapshot(number, table))


def get_table_orders(table_number):
    number, _, table, err = _load_table(table_number)
    if err:
        return err
    orders = [dict(o) for o in table["orders"]]
    return _ok(f"{len(orders)} item(s) on Table {number}.", orders)


def clear_table(table_number):
    """End of the customer session: orders and notes wiped, table available."""
    number, data, table, err = _load_table(table_number)
    if err:
        return err
    table["orders"] = []
    table["notes"] = ""
    table["status"] = "available"
    save_data(data)
    return _ok(f"Table {number} cleared and is now available.", _snapshot(number, table))



# Notes, search, summary

def add_table_note(table_number, note):
    """Set (or replace) the note on a table."""
    number, data, table, err = _load_table(table_number)
    if err:
        return err
    if not isinstance(note, str):
        return _fail("Note must be a string.")
    table["notes"] = note.strip()
    save_data(data)
    return _ok(f"Note saved for Table {number}.", _snapshot(number, table))


def search_item(item_name):
    """Find every table that currently has this item on its order."""
    item_name, err = _parse_item(item_name)
    if err:
        return err
    data = load_data()
    results = []
    for key, table in sorted(data["tables"].items(), key=lambda kv: int(kv[0])):
        entry = _find_item(table["orders"], item_name)
        if entry:
            results.append({"table_number": int(key), "quantity": entry["quantity"]})
    if not results:
        return _ok(f"{item_name} is not on any active table.", [])
    return _ok(f"{item_name} found on {len(results)} table(s).", results)

def phone_has_table(phone):
    """Is mobile number ka active table number, nahi hai to None."""
    if not phone:
        return None
    for key, table in load_data()["tables"].items():
        if table.get("phone") == phone and table["orders"]:
            return int(key)
    return None

def get_summary():
    data = load_data()
    counts = {s: 0 for s in VALID_STATUSES}
    for table in data["tables"].values():
        counts[table["status"]] = counts.get(table["status"], 0) + 1
    summary = {
        "total_tables": len(data["tables"]),
        "available_tables": counts["available"],
        "occupied_tables": counts["occupied"],
        "reserved_tables": counts["reserved"],
        "cleaning_tables": counts["cleaning"],
    }
    return _ok("Restaurant summary.", summary)


