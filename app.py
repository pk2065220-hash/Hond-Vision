import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
import smtplib
from email.message import EmailMessage

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Honda Inventory Management",
    page_icon="🛵",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# DATABASE
# =========================================================

DB_FILE = "honda_inventory.db"

conn = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

c = conn.cursor()


# =========================================================
# CREATE DATABASE TABLES
# =========================================================

def create_tables():

    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            part_no TEXT PRIMARY KEY,
            part_name TEXT NOT NULL,
            category TEXT,
            rack_location TEXT,
            purchase_price REAL DEFAULT 0,
            selling_price REAL DEFAULT 0,
            stock_qty INTEGER DEFAULT 0,
            min_stock_alert INTEGER DEFAULT 5,
            supplier TEXT,
            unit TEXT DEFAULT 'PCS',
            description TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT,
            date TEXT,
            customer_name TEXT,
            mobile TEXT,
            email TEXT,
            address TEXT,
            part_no TEXT,
            part_name TEXT,
            qty INTEGER,
            rate REAL,
            subtotal REAL,
            discount REAL,
            gst_percent REAL,
            gst_amount REAL,
            total_amount REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            supplier TEXT,
            part_no TEXT,
            part_name TEXT,
            qty INTEGER,
            purchase_price REAL,
            gst_percent REAL,
            gst_amount REAL,
            total_amount REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT,
            email TEXT,
            address TEXT,
            gstin TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            business_name TEXT,
            address TEXT,
            phone TEXT,
            email TEXT,
            gstin TEXT,
            invoice_prefix TEXT,
            gst_percent REAL
        )
    """)

    conn.commit()


create_tables()


# =========================================================
# DATABASE MIGRATION
# =========================================================

def add_column_if_missing(table, column, definition):

    columns = [
        row[1]
        for row in c.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    if column not in columns:

        try:

            c.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

            conn.commit()

        except Exception:
            pass


# Inventory upgrades
add_column_if_missing("inventory", "supplier", "TEXT")
add_column_if_missing("inventory", "unit", "TEXT DEFAULT 'PCS'")
add_column_if_missing("inventory", "description", "TEXT")

# Sales upgrades
add_column_if_missing("sales", "invoice_no", "TEXT")
add_column_if_missing("sales", "mobile", "TEXT")
add_column_if_missing("sales", "email", "TEXT")
add_column_if_missing("sales", "address", "TEXT")
add_column_if_missing("sales", "part_name", "TEXT")
add_column_if_missing("sales", "rate", "REAL DEFAULT 0")
add_column_if_missing("sales", "subtotal", "REAL DEFAULT 0")
add_column_if_missing("sales", "discount", "REAL DEFAULT 0")
add_column_if_missing("sales", "gst_percent", "REAL DEFAULT 18")
add_column_if_missing("sales", "gst_amount", "REAL DEFAULT 0")


# =========================================================
# DEFAULT SETTINGS
# =========================================================

default_settings = (
    "HONDA",
    "Puroani Chowk\nLachhuar Road\nSikandra\nJamui, Bihar",
    "",
    "hodahonda2018@gmail.com",
    "",
    "INV",
    18.0
)

existing = c.execute(
    "SELECT id FROM settings WHERE id=1"
).fetchone()

if not existing:

    c.execute("""
        INSERT INTO settings
        (
            id,
            business_name,
            address,
            phone,
            email,
            gstin,
            invoice_prefix,
            gst_percent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (1, *default_settings))

    conn.commit()


def get_settings():

    row = c.execute(
        "SELECT * FROM settings WHERE id=1"
    ).fetchone()

    return {
        "business_name": row[1],
        "address": row[2],
        "phone": row[3],
        "email": row[4],
        "gstin": row[5],
        "invoice_prefix": row[6],
        "gst_percent": row[7]
    }


settings = get_settings()


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def money(value):

    try:
        return f"₹{float(value):,.2f}"

    except Exception:
        return "₹0.00"


def get_inventory():

    return pd.read_sql_query(
        """
        SELECT
            part_no,
            part_name,
            category,
            rack_location,
            purchase_price,
            selling_price,
            stock_qty,
            min_stock_alert,
            supplier,
            unit,
            description
        FROM inventory
        ORDER BY part_name
        """,
        conn
    )


def get_next_invoice_number():

    prefix = settings["invoice_prefix"] or "INV"

    rows = c.execute(
        """
        SELECT invoice_no
        FROM sales
        WHERE invoice_no IS NOT NULL
        """
    ).fetchall()

    highest = 0

    for row in rows:

        try:

            number = int(
                str(row[0]).split("-")[-1]
            )

            highest = max(
                highest,
                number
            )

        except Exception:
            pass

    return f"{prefix}-{highest + 1:05d}"


# =========================================================
# PDF GENERATION
# =========================================================

def create_invoice_pdf(
    invoice_no,
    invoice_date,
    customer_name,
    mobile,
    customer_email,
    address,
    part_no,
    part_name,
    qty,
    rate,
    subtotal,
    discount,
    gst_percent,
    gst_amount,
    total
):

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=35,
        leftMargin=35,
        topMargin=35,
        bottomMargin=35
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        alignment=TA_CENTER,
        fontSize=20,
        leading=24
    )

    center_style = ParagraphStyle(
        "Center",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=10
    )

    right_style = ParagraphStyle(
        "Right",
        parent=styles["Normal"],
        alignment=TA_RIGHT
    )

    story = []

    # Header
    story.append(
        Paragraph(
            settings["business_name"] or "HONDA",
            title_style
        )
    )

    story.append(
        Paragraph(
            "INVOICE / TAX INVOICE",
            center_style
        )
    )

    story.append(Spacer(1, 10))

    business_address = settings["address"].replace(
        "\n",
        "<br/>"
    )

    story.append(
        Paragraph(
            business_address,
            center_style
        )
    )

    if settings["phone"]:

        story.append(
            Paragraph(
                f"Phone: {settings['phone']}",
                center_style
            )
        )

    if settings["email"]:

        story.append(
            Paragraph(
                f"Email: {settings['email']}",
                center_style
            )
        )

    story.append(Spacer(1, 18))

    info = [
        [
            Paragraph(
                f"<b>Invoice No:</b> {invoice_no}",
                styles["Normal"]
            ),
            Paragraph(
                f"<b>Date:</b> {invoice_date}",
                right_style
            )
        ],
        [
            Paragraph(
                f"<b>Customer:</b> {customer_name or '-'}",
                styles["Normal"]
            ),
            Paragraph(
                f"<b>Mobile:</b> {mobile or '-'}",
                right_style
            )
        ],
        [
            Paragraph(
                f"<b>Email:</b> {customer_email or '-'}",
                styles["Normal"]
            ),
            Paragraph(
                f"<b>GST:</b> {gst_percent}%",
                right_style
            )
        ]
    ]

    info_table = Table(
        info,
        colWidths=[280, 210]
    )

    info_table.setStyle(
        TableStyle([
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(info_table)

    if address:

        story.append(
            Paragraph(
                f"<b>Address:</b> {address}",
                styles["Normal"]
            )
        )

    story.append(Spacer(1, 20))

    item_table_data = [
        [
            "Part No.",
            "Part Name",
            "Qty",
            "Rate",
            "Amount"
        ],
        [
            str(part_no),
            str(part_name),
            str(qty),
            money(rate),
            money(subtotal)
        ]
    ]

    item_table = Table(
        item_table_data,
        colWidths=[
            80,
            190,
            50,
            90,
            90
        ]
    )

    item_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#e60012")
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.grey
            ),
            (
                "ALIGN",
                (2, 1),
                (-1, -1),
                "RIGHT"
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                8
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8
            )
        ])
    )

    story.append(item_table)

    story.append(Spacer(1, 20))

    totals = [
        ["Subtotal", money(subtotal)],
        ["Discount", money(discount)],
        [
            f"GST ({gst_percent}%)",
            money(gst_amount)
        ],
        ["TOTAL", money(total)]
    ]

    totals_table = Table(
        totals,
        colWidths=[390, 120],
        hAlign="RIGHT"
    )

    totals_table.setStyle(
        TableStyle([
            (
                "ALIGN",
                (1, 0),
                (1, -1),
                "RIGHT"
            ),
            (
                "LINEABOVE",
                (0, -1),
                (-1, -1),
                1
            ),
            (
                "FONTNAME",
                (0, -1),
                (-1, -1),
                "Helvetica-Bold"
            ),
            (
                "FONTSIZE",
                (0, -1),
                (-1, -1),
                13
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(totals_table)

    story.append(Spacer(1, 35))

    story.append(
        Paragraph(
            "<b>Thank You for your business!</b>",
            center_style
        )
    )

    document.build(story)

    buffer.seek(0)

    return buffer.getvalue()


# =========================================================
# EMAIL
# =========================================================

def send_invoice_email(
    customer_email,
    invoice_no,
    pdf_bytes
):

    if not customer_email:

        return (
            False,
            "Customer email नहीं दिया गया."
        )

    try:

        sender_email = st.secrets["SMTP_EMAIL"]

        sender_password = st.secrets[
            "SMTP_PASSWORD"
        ]

        smtp_server = st.secrets.get(
            "SMTP_SERVER",
            "smtp.gmail.com"
        )

        smtp_port = int(
            st.secrets.get(
                "SMTP_PORT",
                587
            )
        )

    except Exception:

        return (
            False,
            "Streamlit Secrets में Gmail settings नहीं मिलीं."
        )

    try:

        message = EmailMessage()

        message["Subject"] = (
            f"HONDA Invoice {invoice_no}"
        )

        message["From"] = sender_email

        message["To"] = customer_email

        message.set_content(
            f"""
Dear Customer,

Please find attached your HONDA Invoice.

Invoice Number: {invoice_no}

Thank you for your business.

HONDA
Puroani Chowk
Lachhuar Road
Sikandra
Jamui, Bihar

Email: {sender_email}
"""
        )

        message.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=f"{invoice_no}.pdf"
        )

        with smtplib.SMTP(
            smtp_server,
            smtp_port,
            timeout=30
        ) as server:

            server.starttls()

            server.login(
                sender_email,
                sender_password
            )

            server.send_message(
                message
            )

        return (
            True,
            "Invoice successfully emailed."
        )

    except Exception as error:

        return (
            False,
            f"Email error: {error}"
        )


# =========================================================
# CSS
# =========================================================

st.markdown(
    """
<style>

.main {
    background-color: #f5f6f8;
}

.block-container {
    padding-top: 1rem;
}

.honda-header {
    background: linear-gradient(
        90deg,
        #d90416,
        #ed1c24
    );

    color: white;

    padding: 24px;

    border-radius: 15px;

    margin-bottom: 20px;
}

.honda-header h1 {
    margin: 0;
}

</style>
""",
    unsafe_allow_html=True
)


# =========================================================
# HEADER
# =========================================================

st.markdown(
    """
<div class="honda-header">

<h1>🛵 HONDA Inventory Management</h1>

<p>
Inventory • Purchase • Sales • Billing • Invoice • Reports
</p>

</div>
""",
    unsafe_allow_html=True
)


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.title("🛵 HONDA")

menu = st.sidebar.radio(
    "Navigation",
    [
        "📊 Dashboard",
        "📦 Inventory",
        "🛒 Purchase",
        "🧾 Sales & Invoice",
        "👤 Customers",
        "📈 Reports",
        "⚙️ Settings"
    ]
)


# =========================================================
# DASHBOARD
# =========================================================

if menu == "📊 Dashboard":

    st.subheader(
        "📊 Dashboard"
    )

    inventory = get_inventory()

    total_items = len(inventory)

    total_stock = (
        int(
            inventory["stock_qty"].sum()
        )
        if not inventory.empty
        else 0
    )

    low_stock = (
        inventory[
            inventory["stock_qty"]
            <= inventory["min_stock_alert"]
        ]
        if not inventory.empty
        else pd.DataFrame()
    )

    sales = pd.read_sql_query(
        "SELECT * FROM sales",
        conn
    )

    total_sales = (
        float(
            sales["total_amount"].sum()
        )
        if not sales.empty
        else 0
    )

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    today_sales = 0

    if not sales.empty:

        today_sales = float(
            sales[
                sales["date"].str.startswith(
                    today
                )
            ]["total_amount"].sum()
        )

    a, b, c1, d = st.columns(4)

    a.metric(
        "📦 Total Items",
        total_items
    )

    b.metric(
        "🔢 Total Stock",
        total_stock
    )

    c1.metric(
        "💰 Total Sales",
        money(total_sales)
    )

    d.metric(
        "🔴 Low Stock",
        len(low_stock)
    )

    st.markdown("---")

    x, y = st.columns(2)

    x.metric(
        "Today's Sales",
        money(today_sales)
    )

    y.metric(
        "Total Invoices",
        len(sales)
    )

    if not low_stock.empty:

        st.warning(
            "⚠️ Low Stock Alert"
        )

        st.dataframe(
            low_stock,
            use_container_width=True,
            hide_index=True
        )

    st.subheader(
        "Recent Sales"
    )

    if not sales.empty:

        st.dataframe(
            sales.sort_values(
                "sale_id",
                ascending=False
            ).head(10),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "अभी कोई sales नहीं है."
        )


# =========================================================
# INVENTORY
# =========================================================

elif menu == "📦 Inventory":

    st.subheader(
        "📦 Inventory Management"
    )

    with st.expander(
        "➕ Add New Item"
    ):

        with st.form(
            "add_inventory"
        ):

            col1, col2 = st.columns(2)

            with col1:

                part_no = st.text_input(
                    "Part Number / Chassis Number"
                )

                part_name = st.text_input(
                    "Part / Model Name"
                )

                category = st.text_input(
                    "Category",
                    "Spare Parts"
                )

                rack = st.text_input(
                    "Rack Location",
                    "A-1"
                )

                supplier = st.text_input(
                    "Supplier"
                )

            with col2:

                purchase_price = st.number_input(
                    "Purchase Price ₹",
                    min_value=0.0,
                    step=1.0
                )

                selling_price = st.number_input(
                    "Selling Price ₹",
                    min_value=0.0,
                    step=1.0
                )

                quantity = st.number_input(
                    "Stock Quantity",
                    min_value=0,
                    step=1
                )

                minimum = st.number_input(
                    "Minimum Stock Alert",
                    min_value=1,
                    value=5,
                    step=1
                )

                unit = st.text_input(
                    "Unit",
                    "PCS"
                )

            description = st.text_area(
                "Description"
            )

            save = st.form_submit_button(
                "💾 Save Item"
            )

            if save:

                if not part_no or not part_name:

                    st.error(
                        "Part Number और Part Name जरूरी हैं."
                    )

                else:

                    try:

                        c.execute(
                            """
                            INSERT INTO inventory
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                part_no,
                                part_name,
                                category,
                                rack,
                                purchase_price,
                                selling_price,
                                quantity,
                                minimum,
                                supplier,
                                unit,
                                description
                            )
                        )

                        conn.commit()

                        st.success(
                            "✅ Item successfully added."
                        )

                    except sqlite3.IntegrityError:

                        st.error(
                            "यह Part Number पहले से मौजूद है."
                        )

    st.subheader(
        "Current Inventory"
    )

    inventory = get_inventory()

    if not inventory.empty:

        search = st.text_input(
            "🔎 Search Inventory"
        )

        if search:

            mask = (
                inventory.astype(str)
                .apply(
                    lambda row:
                    row.str.contains(
                        search,
                        case=False,
                        na=False
                    ).any(),
                    axis=1
                )
            )

            inventory = inventory[mask]

        st.dataframe(
            inventory,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Inventory खाली है."
        )


# =========================================================
# PURCHASE
# =========================================================

elif menu == "🛒 Purchase":

    st.subheader(
        "🛒 Purchase Entry"
    )

    inventory = get_inventory()

    if inventory.empty:

        st.warning(
            "पहले Inventory में item add करें."
        )

    else:

        selected = st.selectbox(
            "Select Part",
            inventory["part_name"].tolist()
        )

        item = inventory[
            inventory["part_name"] == selected
        ].iloc[0]

        quantity = st.number_input(
            "Quantity Added",
            min_value=1,
            step=1
        )

        price = st.number_input(
            "Purchase Price ₹",
            min_value=0.0,
            value=float(
                item["purchase_price"]
            ),
            step=1.0
        )

        supplier = st.text_input(
            "Supplier",
            value=str(
                item["supplier"] or ""
            )
        )

        gst = st.number_input(
            "GST %",
            min_value=0.0,
            max_value=100.0,
            value=float(
                settings["gst_percent"]
            )
        )

        subtotal = quantity * price

        gst_amount = (
            subtotal * gst / 100
        )

        total = (
            subtotal + gst_amount
        )

        st.write(
            f"Subtotal: **{money(subtotal)}**"
        )

        st.write(
            f"GST: **{money(gst_amount)}**"
        )

        st.write(
            f"Total: **{money(total)}**"
        )

        if st.button(
            "➕ Save Purchase",
            type="primary"
        ):

            c.execute(
                """
                UPDATE inventory
                SET
                    stock_qty = stock_qty + ?,
                    purchase_price = ?,
                    supplier = ?
                WHERE part_no = ?
                """,
                (
                    quantity,
                    price,
                    supplier,
                    item["part_no"]
                )
            )

            c.execute(
                """
                INSERT INTO purchases
                (
                    date,
                    supplier,
                    part_no,
                    part_name,
                    qty,
                    purchase_price,
                    gst_percent,
                    gst_amount,
                    total_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    supplier,
                    item["part_no"],
                    item["part_name"],
                    quantity,
                    price,
                    gst,
                    gst_amount,
                    total
                )
            )

            conn.commit()

            st.success(
                "✅ Purchase saved and stock increased."
            )

    purchases = pd.read_sql_query(
        """
        SELECT *
        FROM purchases
        ORDER BY purchase_id DESC
        """,
        conn
    )

    if not purchases.empty:

        st.subheader(
            "Purchase History"
        )

        st.dataframe(
            purchases,
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# SALES & INVOICE
# =========================================================

elif menu == "🧾 Sales & Invoice":

    st.subheader(
        "🧾 Sales & Invoice"
    )

    inventory = get_inventory()

    inventory = inventory[
        inventory["stock_qty"] > 0
    ]

    if inventory.empty:

        st.warning(
            "कोई stock available नहीं है."
        )

    else:

        col1, col2 = st.columns(2)

        with col1:

            customer_name = st.text_input(
                "Customer Name"
            )

            mobile = st.text_input(
                "Mobile Number"
            )

            customer_email = st.text_input(
                "Customer Email"
            )

        with col2:

            customer_address = st.text_area(
                "Customer Address"
            )

            selected_part = st.selectbox(
                "Select Part / Model",
                inventory["part_name"].tolist()
            )

        item = inventory[
            inventory["part_name"]
            == selected_part
        ].iloc[0]

        st.info(
            f"Available: {item['stock_qty']} | "
            f"Rate: {money(item['selling_price'])} | "
            f"Rack: {item['rack_location']}"
        )

        quantity = st.number_input(
            "Quantity",
            min_value=1,
            max_value=int(
                item["stock_qty"]
            ),
            value=1,
            step=1
        )

        rate = st.number_input(
            "Rate ₹",
            min_value=0.0,
            value=float(
                item["selling_price"]
            ),
            step=1.0
        )

        discount = st.number_input(
            "Discount ₹",
            min_value=0.0,
            value=0.0,
            step=1.0
        )

        gst_percent = st.number_input(
            "GST %",
            min_value=0.0,
            max_value=100.0,
            value=float(
                settings["gst_percent"]
            )
        )

        subtotal = quantity * rate

        taxable = max(
            subtotal - discount,
            0
        )

        gst_amount = (
            taxable * gst_percent / 100
        )

        total = taxable + gst_amount

        a, b, c1, d = st.columns(4)

        a.metric(
            "Subtotal",
            money(subtotal)
        )

        b.metric(
            "Discount",
            money(discount)
        )

        c1.metric(
            "GST",
            money(gst_amount)
        )

        d.metric(
            "TOTAL",
            money(total)
        )

        invoice_preview = (
            get_next_invoice_number()
        )

        st.info(
            f"Invoice No: **{invoice_preview}**"
        )

        if st.button(
            "🧾 CREATE INVOICE",
            type="primary",
            use_container_width=True
        ):

            invoice_no = (
                get_next_invoice_number()
            )

            invoice_date = datetime.now().strftime(
                "%d-%m-%Y"
            )

            # Reduce stock
            c.execute(
                """
                UPDATE inventory
                SET stock_qty = stock_qty - ?
                WHERE part_no = ?
                """,
                (
                    quantity,
                    item["part_no"]
                )
            )

            # Save sale
            c.execute(
                """
                INSERT INTO sales
                (
                    invoice_no,
                    date,
                    customer_name,
                    mobile,
                    email,
                    address,
                    part_no,
                    part_name,
                    qty,
                    rate,
                    subtotal,
                    discount,
                    gst_percent,
                    gst_amount,
                    total_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_no,
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    customer_name,
                    mobile,
                    customer_email,
                    customer_address,
                    item["part_no"],
                    item["part_name"],
                    quantity,
                    rate,
                    subtotal,
                    discount,
                    gst_percent,
                    gst_amount,
                    total
                )
            )

            # Save customer
            if customer_name:

                c.execute(
                    """
                    INSERT INTO customers
                    (
                        name,
                        mobile,
                        email,
                        address
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        customer_name,
                        mobile,
                        customer_email,
                        customer_address
                    )
                )

            conn.commit()

            pdf = create_invoice_pdf(
                invoice_no,
                invoice_date,
                customer_name,
                mobile,
                customer_email,
                customer_address,
                item["part_no"],
                item["part_name"],
                quantity,
                rate,
                subtotal,
                discount,
                gst_percent,
                gst_amount,
                total
            )

            st.session_state[
                "invoice_pdf"
            ] = pdf

            st.session_state[
                "invoice_number"
            ] = invoice_no

            st.session_state[
                "customer_email"
            ] = customer_email

            st.success(
                f"✅ Invoice {invoice_no} created successfully."
            )

        if "invoice_pdf" in st.session_state:

            st.markdown("---")

            pdf = st.session_state[
                "invoice_pdf"
            ]

            invoice_no = st.session_state[
                "invoice_number"
            ]

            st.download_button(
                "📄 Download Invoice PDF",
                data=pdf,
                file_name=f"{invoice_no}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

            st.subheader(
                "📧 Automatic Email"
            )

            email_to = st.text_input(
                "Customer Email",
                value=st.session_state.get(
                    "customer_email",
                    ""
                )
            )

            if st.button(
                "📧 Send Invoice Automatically",
                use_container_width=True
            ):

                success, message = (
                    send_invoice_email(
                        email_to,
                        invoice_no,
                        pdf
                    )
                )

                if success:

                    st.success(
                        "✅ " + message
                    )

                else:

                    st.error(
                        "❌ " + message
                    )

    st.subheader(
        "Recent Invoices"
    )

    sales = pd.read_sql_query(
        """
        SELECT
            invoice_no,
            date,
            customer_name,
            mobile,
            email,
            part_name,
            qty,
            rate,
            subtotal,
            discount,
            gst_amount,
            total_amount
        FROM sales
        ORDER BY sale_id DESC
        LIMIT 100
        """,
        conn
    )

    if not sales.empty:

        st.dataframe(
            sales,
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# CUSTOMERS
# =========================================================

elif menu == "👤 Customers":

    st.subheader(
        "👤 Customer Management"
    )

    with st.form(
        "customer_form"
    ):

        name = st.text_input(
            "Customer Name"
        )

        mobile = st.text_input(
            "Mobile"
        )

        email = st.text_input(
            "Email"
        )

        address = st.text_area(
            "Address"
        )

        gstin = st.text_input(
            "GSTIN"
        )

        save_customer = (
            st.form_submit_button(
                "💾 Save Customer"
            )
        )

        if save_customer:

            if not name:

                st.error(
                    "Customer name जरूरी है."
                )

            else:

                c.execute(
                    """
                    INSERT INTO customers
                    (
                        name,
                        mobile,
                        email,
                        address,
                        gstin
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        mobile,
                        email,
                        address,
                        gstin
                    )
                )

                conn.commit()

                st.success(
                    "✅ Customer saved."
                )

    customers = pd.read_sql_query(
        """
        SELECT *
        FROM customers
        ORDER BY customer_id DESC
        """,
        conn
    )

    if not customers.empty:

        st.dataframe(
            customers,
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# REPORTS
# =========================================================

elif menu == "📈 Reports":

    st.subheader(
        "📈 Reports"
    )

    tab1, tab2, tab3 = st.tabs(
        [
            "Sales",
            "Purchase",
            "Stock"
        ]
    )

    with tab1:

        sales = pd.read_sql_query(
            """
            SELECT *
            FROM sales
            ORDER BY sale_id DESC
            """,
            conn
        )

        if not sales.empty:

            st.metric(
                "Total Sales",
                money(
                    sales["total_amount"].sum()
                )
            )

            st.dataframe(
                sales,
                use_container_width=True,
                hide_index=True
            )

            csv = sales.to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "⬇️ Download Sales CSV",
                csv,
                "sales_report.csv",
                "text/csv"
            )

    with tab2:

        purchases = pd.read_sql_query(
            """
            SELECT *
            FROM purchases
            ORDER BY purchase_id DESC
            """,
            conn
        )

        if not purchases.empty:

            st.dataframe(
                purchases,
                use_container_width=True,
                hide_index=True
            )

            csv = purchases.to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "⬇️ Download Purchase CSV",
                csv,
                "purchase_report.csv",
                "text/csv"
            )

    with tab3:

        inventory = get_inventory()

        if not inventory.empty:

            st.dataframe(
                inventory,
                use_container_width=True,
                hide_index=True
            )

            csv = inventory.to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "⬇️ Download Stock CSV",
                csv,
                "stock_report.csv",
                "text/csv"
            )


# =========================================================
# SETTINGS
# =========================================================

elif menu == "⚙️ Settings":

    st.subheader(
        "⚙️ Business Settings"
    )

    current = get_settings()

    business_name = st.text_input(
        "Business Name",
        current["business_name"]
    )

    address = st.text_area(
        "Business Address",
        current["address"]
    )

    phone = st.text_input(
        "Business Phone",
        current["phone"]
    )

    email = st.text_input(
        "Business Email",
        current["email"]
    )

    gstin = st.text_input(
        "GSTIN",
        current["gstin"]
    )

    invoice_prefix = st.text_input(
        "Invoice Prefix",
        current["invoice_prefix"]
    )

    gst_percent = st.number_input(
        "Default GST %",
        min_value=0.0,
        max_value=100.0,
        value=float(
            current["gst_percent"]
        )
    )

    if st.button(
        "💾 Save Settings",
        type="primary"
    ):

        c.execute(
            """
            UPDATE settings
            SET
                business_name=?,
                address=?,
                phone=?,
                email=?,
                gstin=?,
                invoice_prefix=?,
                gst_percent=?
            WHERE id=1
            """,
            (
                business_name,
                address,
                phone,
                email,
                gstin,
                invoice_prefix,
                gst_percent
            )
        )

        conn.commit()

        settings = get_settings()

        st.success(
            "✅ Settings saved successfully."
        )

    st.markdown("---")

    st.subheader(
        "📧 Gmail Automatic Invoice"
    )

    st.info(
        """
Automatic invoice email के लिए Streamlit Secrets में
Gmail SMTP credentials configure करें.
"""
    )

    st.code(
        """
SMTP_EMAIL = "hodahonda2018@gmail.com"
SMTP_PASSWORD = "YOUR_GMAIL_APP_PASSWORD"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
""",
        language="toml"
    )

    st.warning(
        "⚠️ Gmail password या App Password को app.py या GitHub में मत डालें."
    )


# =========================================================
# SIDEBAR FOOTER
# =========================================================

st.sidebar.markdown("---")

st.sidebar.caption(
    "HONDA Inventory Management"
)

st.sidebar.caption(
    "Inventory • Billing • PDF • Email"
)
