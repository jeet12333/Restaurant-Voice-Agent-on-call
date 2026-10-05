
import streamlit as st

import backend as rb  # <- your backend file (rename the import if needed)

st.set_page_config(page_title="Restaurant Manager", page_icon="🍽️", layout="wide")

STATUS_ICON = {"available": "🟢", "occupied": "🔴", "reserved": "🟡", "cleaning": "🔵"}
PAGES = ["📊 Floor", "🪑 Manage Table", "🔍 Search Item", "⚙️ Setup"]



# Helpers

def flash(result):
    st.session_state["flash"] = (result["success"], result["message"])


def act(fn, *args):
    """Run a backend call, store its message, and refresh the page."""
    flash(fn(*args))
    st.rerun()


def show_flash():
    msg = st.session_state.pop("flash", None)
    if msg:
        ok, text = msg
        (st.success if ok else st.error)(text)


def open_table(number):
    st.session_state["selected_table"] = number
    st.session_state["page"] = PAGES[1]


def table_numbers():
    return [r["table_number"] for r in rb.view_all_tables()["data"]]



# Pages

def page_floor():
    st.header("Floor overview")
    s = rb.get_summary()["data"]
    c = st.columns(5)
    c[0].metric("Total", s["total_tables"])
    c[1].metric("🟢 Available", s["available_tables"])
    c[2].metric("🔴 Occupied", s["occupied_tables"])
    c[3].metric("🟡 Reserved", s["reserved_tables"])
    c[4].metric("🔵 Cleaning", s["cleaning_tables"])
    st.divider()

    rows = rb.view_all_tables()["data"]
    if not rows:
        st.info("No tables yet. Add some in the **Setup** page.")
        return

    per_row = 4
    for i in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for col, row in zip(cols, rows[i:i + per_row]):
            n, status = row["table_number"], row["status"]
            detail = rb.view_table(n)["data"]
            items = sum(o["quantity"] for o in detail["orders"])
            with col.container(border=True):
                st.subheader(f"Table {n}")
                st.write(f"{STATUS_ICON.get(status, '⚪')} **{status.title()}**")
                st.caption(f"{items} item(s) ordered")
                st.button("Open", key=f"open_{n}", on_click=open_table,
                          args=(n,), use_container_width=True)


def page_manage():
    st.header("Manage table")
    numbers = table_numbers()
    if not numbers:
        st.info("No tables yet. Add some in the **Setup** page.")
        return

    if st.session_state.get("selected_table") not in numbers:
        st.session_state["selected_table"] = numbers[0]
    n = st.selectbox("Table", numbers, key="selected_table",
                     format_func=lambda x: f"Table {x}")

    detail = rb.view_table(n)["data"]
    status = detail["status"]
    check = rb.check_table_status(n)["data"]

    top = st.columns([1, 1, 2])
    top[0].metric("Status", f"{STATUS_ICON[status]} {status.title()}")
    top[1].metric("Items", sum(o["quantity"] for o in detail["orders"]))
    if detail["notes"]:
        top[2].info(f"📝 {detail['notes']}")

    left, right = st.columns(2, gap="large")

    #  Orders 
    with left:
        st.subheader("Orders")
        if detail["orders"]:
            st.dataframe(
                [{"Item": o["item"], "Qty": o["quantity"]} for o in detail["orders"]],
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("No items on this table.")

        st.markdown("**Add item**")
        if not check["can_add_order"]:
            st.warning(f"Table is {status}; orders can't be added right now.")
        with st.form("add_form", clear_on_submit=True):
            item = st.text_input("Item name")
            qty = st.number_input("Quantity", min_value=1, step=1, value=1)
            if st.form_submit_button("➕ Add to order", disabled=not check["can_add_order"]):
                act(rb.add_order, n, item, int(qty))

        if detail["orders"]:
            st.markdown("**Edit / remove item**")
            names = [o["item"] for o in detail["orders"]]
            chosen = st.selectbox("Item", names, key=f"edit_item_{n}")
            current = next(o["quantity"] for o in detail["orders"] if o["item"] == chosen)
            new_qty = st.number_input("New quantity", min_value=1, step=1,
                                      value=int(current), key=f"edit_qty_{n}_{chosen}")
            b1, b2 = st.columns(2)
            if b1.button("✏️ Update quantity", use_container_width=True):
                act(rb.edit_order, n, chosen, int(new_qty))
            if b2.button("🗑️ Remove item", use_container_width=True):
                act(rb.remove_order, n, chosen)

    #  Status / notes / danger 
    with right:
        st.subheader("Status")
        options = list(rb.VALID_STATUSES)
        new_status = st.selectbox("Set status", options, index=options.index(status),
                                  format_func=str.title, key=f"status_{n}_{status}")
        if st.button("Update status"):
            act(rb.update_table_status, n, new_status)

        st.subheader("Notes")
        note = st.text_area("Table note", value=detail["notes"],
                            key=f"note_{n}_{detail['notes']}", height=100,
                            placeholder="Allergies, birthday, special requests…")
        if st.button("💾 Save note"):
            act(rb.add_table_note, n, note)

        st.subheader("Session")
        if st.button("🧹 Clear table (end session)", use_container_width=True):
            act(rb.clear_table, n)


def page_search():
    st.header("Search item")
    st.caption("Find every table currently ordering a given item.")
    with st.form("search_form"):
        name = st.text_input("Item name")
        go = st.form_submit_button("🔍 Search")
    if go:
        res = rb.search_item(name)
        (st.success if res["success"] else st.error)(res["message"])
        if res["data"]:
            st.dataframe(
                [{"Table": r["table_number"], "Quantity": r["quantity"]} for r in res["data"]],
                hide_index=True, use_container_width=True,
            )


def page_setup():
    st.header("Setup")
    st.subheader("Add table")
    with st.form("create_form", clear_on_submit=True):
        num = st.number_input("Table number", min_value=1, step=1, value=1)
        if st.form_submit_button("➕ Create table"):
            act(rb.create_table, int(num))

    st.subheader("Delete table")
    numbers = table_numbers()
    if not numbers:
        st.caption("No tables to delete.")
        return
    target = st.selectbox("Table to delete", numbers, format_func=lambda x: f"Table {x}")
    confirm = st.checkbox("I'm sure I want to delete this table")
    if st.button("🗑️ Delete table", disabled=not confirm):
        act(rb.delete_table, target)
    st.caption("A table with active orders can't be deleted. Clear it first.")



# Router

st.title("🍽️ Restaurant Manager")
st.sidebar.radio("Navigate", PAGES, key="page")
st.sidebar.divider()
if st.sidebar.button("🔄 Refresh"):
    st.rerun()

show_flash()

{
    PAGES[0]: page_floor,
    PAGES[1]: page_manage,
    PAGES[2]: page_search,
    PAGES[3]: page_setup,
}[st.session_state["page"]]()