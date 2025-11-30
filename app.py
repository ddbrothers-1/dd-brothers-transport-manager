
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from datetime import datetime, date
from functools import wraps
import sqlite3
import os
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors

APP_SECRET_KEY = "super_secret_dd_brothers_key"
ADMIN_USERNAME = "DD_Brothers"
ADMIN_PASSWORD = "Ash#1Laddi"
ACTION_PASSWORD = "1322420"
DB_NAME = "dd_brothers.db"
HST_RATE = 0.13

app = Flask(__name__)
app.secret_key = APP_SECRET_KEY


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            main_category TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            truck_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            includes_hst INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL,
            edited INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (truck_id) REFERENCES trucks(id),
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
        """
    )
    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("home"))
        flash("Invalid admin or password.", "danger")
    return render_template("login.html", admin_username=ADMIN_USERNAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT IFNULL(SUM(amount),0) AS total_income FROM entries WHERE main_category='Income'")
    total_income = cur.fetchone()["total_income"]

    cur.execute("SELECT IFNULL(SUM(amount),0) AS total_expense FROM entries WHERE main_category='Expense'")
    total_expense = cur.fetchone()["total_expense"]

    net_income = total_income - total_expense

    cur.execute("SELECT COUNT(*) AS active_trucks FROM trucks WHERE active=1")
    active_trucks = cur.fetchone()["active_trucks"]

    cur.execute("SELECT COUNT(*) AS active_drivers FROM drivers WHERE active=1")
    active_drivers = cur.fetchone()["active_drivers"]

    conn.close()
    return render_template(
        "home.html",
        total_income=total_income,
        total_expense=total_expense,
        net_income=net_income,
        active_trucks=active_trucks,
        active_drivers=active_drivers,
    )


@app.route("/expense-income", methods=["GET", "POST"])
@login_required
def expense_income():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM trucks WHERE active=1 ORDER BY number")
    trucks = cur.fetchall()
    cur.execute("SELECT * FROM drivers WHERE active=1 ORDER BY name")
    drivers = cur.fetchall()

    if request.method == "POST":
        main_category = request.form.get("category")
        sub_category = request.form.get("type")
        truck_id = request.form.get("truck_id")
        driver_id = request.form.get("driver_id")
        amount = request.form.get("amount")
        date_str = request.form.get("date")
        description = request.form.get("description")
        includes_hst_value = request.form.get("includes_hst")

        missing = []
        if not main_category:
            missing.append("Category")
        if not sub_category:
            missing.append("Type")
        if not truck_id:
            missing.append("Truck")
        if not driver_id:
            missing.append("Driver")
        if not amount:
            missing.append("Amount")
        if not date_str:
            missing.append("Date")
        if not description:
            missing.append("Description")
        if not includes_hst_value:
            missing.append("HST includes")

        try:
            if amount:
                float(amount)
        except ValueError:
            flash("Amount must be a number.", "danger")
            return redirect(url_for("expense_income"))

        includes_hst_flag = includes_hst_value == "yes"

        if missing:
            flash("Please fill: " + ", ".join(missing), "danger")
        else:
            now = datetime.now().isoformat(sep=" ", timespec="seconds")
            cur.execute(
                """
                INSERT INTO entries
                (main_category, sub_category, truck_id, driver_id, amount, date,
                 includes_hst, description, edited, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,0,?,?)
                """,
                (
                    main_category,
                    sub_category,
                    int(truck_id),
                    int(driver_id),
                    float(amount),
                    date_str,
                    1 if includes_hst_flag else 0,
                    description,
                    now,
                    now,
                ),
            )
            conn.commit()
            flash("Entry saved successfully.", "success")
            return redirect(url_for("expense_income"))

    cur.execute(
        """
        SELECT e.*, t.number AS truck_number, d.name AS driver_name
        FROM entries e
        JOIN trucks t ON e.truck_id = t.id
        JOIN drivers d ON e.driver_id = d.id
        ORDER BY date(e.date) DESC, e.id DESC
        """
    )
    entries = cur.fetchall()
    conn.close()
    return render_template("expense_income.html", trucks=trucks, drivers=drivers, entries=entries)


def check_action_password(pwd: str) -> bool:
    return pwd == ACTION_PASSWORD


@app.route("/entry/<int:entry_id>/delete")
@login_required
def delete_entry(entry_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. Entry was not deleted.", "danger")
        return redirect(url_for("expense_income"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM entries WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()
    flash("Entry deleted.", "success")
    return redirect(url_for("expense_income"))


@app.route("/entry/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def edit_entry(entry_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. You cannot edit this entry.", "danger")
        return redirect(url_for("expense_income"))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM trucks WHERE active=1 ORDER BY number")
    trucks = cur.fetchall()
    cur.execute("SELECT * FROM drivers WHERE active=1 ORDER BY name")
    drivers = cur.fetchall()

    cur.execute("SELECT * FROM entries WHERE id=?", (entry_id,))
    entry = cur.fetchone()
    if not entry:
        conn.close()
        flash("Entry not found.", "danger")
        return redirect(url_for("expense_income"))

    if request.method == "POST":
        main_category = request.form.get("category")
        sub_category = request.form.get("type")
        truck_id = request.form.get("truck_id")
        driver_id = request.form.get("driver_id")
        amount = request.form.get("amount")
        date_str = request.form.get("date")
        description = request.form.get("description")
        includes_hst_value = request.form.get("includes_hst")

        missing = []
        if not main_category:
            missing.append("Category")
        if not sub_category:
            missing.append("Type")
        if not truck_id:
            missing.append("Truck")
        if not driver_id:
            missing.append("Driver")
        if not amount:
            missing.append("Amount")
        if not date_str:
            missing.append("Date")
        if not description:
            missing.append("Description")
        if not includes_hst_value:
            missing.append("HST includes")

        try:
            if amount:
                float(amount)
        except ValueError:
            flash("Amount must be a number.", "danger")
            return redirect(url_for("expense_income"))

        includes_hst_flag = includes_hst_value == "yes"

        if missing:
            flash("Please fill: " + ", ".join(missing), "danger")
        else:
            now = datetime.now().isoformat(sep=" ", timespec="seconds")
            cur.execute(
                """
                UPDATE entries
                SET main_category=?, sub_category=?, truck_id=?, driver_id=?,
                    amount=?, date=?, includes_hst=?, description=?, edited=1, updated_at=?
                WHERE id=?
                """,
                (
                    main_category,
                    sub_category,
                    int(truck_id),
                    int(driver_id),
                    float(amount),
                    date_str,
                    1 if includes_hst_flag else 0,
                    description,
                    now,
                    entry_id,
                ),
            )
            conn.commit()
            conn.close()
            flash("Entry updated.", "success")
            return redirect(url_for("expense_income"))

    conn.close()
    return render_template("edit_entry.html", entry=entry, trucks=trucks, drivers=drivers)


@app.route("/trucks", methods=["GET", "POST"])
@login_required
def trucks():
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        number = request.form.get("number", "").strip()
        if not number:
            flash("Truck number is required.", "danger")
        elif not number.isdigit():
            flash("Truck number must be numbers only.", "danger")
        else:
            try:
                cur.execute("INSERT INTO trucks (number, active) VALUES (?,1)", (number,))
                conn.commit()
                flash("Truck added successfully.", "success")
            except sqlite3.IntegrityError:
                flash("Truck already in the system.", "warning")

    cur.execute("SELECT * FROM trucks ORDER BY number")
    trucks_list = cur.fetchall()
    conn.close()
    return render_template("trucks.html", trucks=trucks_list)


@app.route("/truck/<int:truck_id>/toggle")
@login_required
def toggle_truck(truck_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. Truck status not changed.", "danger")
        return redirect(url_for("trucks"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT active FROM trucks WHERE id=?", (truck_id,))
    row = cur.fetchone()
    if row:
        new_status = 0 if row["active"] == 1 else 1
        cur.execute("UPDATE trucks SET active=? WHERE id=?", (new_status, truck_id))
        conn.commit()
    conn.close()
    return redirect(url_for("trucks"))


@app.route("/truck/<int:truck_id>/delete")
@login_required
def delete_truck(truck_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. Truck was not deleted.", "danger")
        return redirect(url_for("trucks"))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM trucks WHERE id=?", (truck_id,))
        conn.commit()
        flash("Truck deleted.", "success")
    except sqlite3.IntegrityError:
        flash("Cannot delete this truck because it is used in entries.", "danger")
    finally:
        conn.close()
    return redirect(url_for("trucks"))


@app.route("/truck/<int:truck_id>/edit", methods=["GET", "POST"])
@login_required
def edit_truck(truck_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. You cannot edit this truck.", "danger")
        return redirect(url_for("trucks"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trucks WHERE id=?", (truck_id,))
    truck = cur.fetchone()
    if not truck:
        conn.close()
        flash("Truck not found.", "danger")
        return redirect(url_for("trucks"))

    if request.method == "POST":
        number = request.form.get("number", "").strip()
        if not number:
            flash("Truck number is required.", "danger")
        elif not number.isdigit():
            flash("Truck number must be numbers only.", "danger")
        else:
            try:
                cur.execute("UPDATE trucks SET number=? WHERE id=?", (number, truck_id))
                conn.commit()
                conn.close()
                flash("Truck updated successfully.", "success")
                return redirect(url_for("trucks"))
            except sqlite3.IntegrityError:
                flash("Another truck with this number already exists.", "danger")

    conn.close()
    return render_template("edit_truck.html", truck=truck)


@app.route("/drivers", methods=["GET", "POST"])
@login_required
def drivers():
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Driver name is required.", "danger")
        else:
            try:
                cur.execute("INSERT INTO drivers (name, active) VALUES (?,1)", (name,))
                conn.commit()
                flash("Driver added successfully.", "success")
            except sqlite3.IntegrityError:
                flash("Driver already in the system.", "warning")

    cur.execute("SELECT * FROM drivers ORDER BY name")
    drivers_list = cur.fetchall()
    conn.close()
    return render_template("drivers.html", drivers=drivers_list)


@app.route("/driver/<int:driver_id>/toggle")
@login_required
def toggle_driver(driver_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. Driver status not changed.", "danger")
        return redirect(url_for("drivers"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT active FROM drivers WHERE id=?", (driver_id,))
    row = cur.fetchone()
    if row:
        new_status = 0 if row["active"] == 1 else 1
        cur.execute("UPDATE drivers SET active=? WHERE id=?", (new_status, driver_id))
        conn.commit()
    conn.close()
    return redirect(url_for("drivers"))


@app.route("/driver/<int:driver_id>/delete")
@login_required
def delete_driver(driver_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. Driver was not deleted.", "danger")
        return redirect(url_for("drivers"))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM drivers WHERE id=?", (driver_id,))
        conn.commit()
        flash("Driver deleted.", "success")
    except sqlite3.IntegrityError:
        flash("Cannot delete this driver because they are used in entries.", "danger")
    finally:
        conn.close()
    return redirect(url_for("drivers"))


@app.route("/driver/<int:driver_id>/edit", methods=["GET", "POST"])
@login_required
def edit_driver(driver_id):
    pwd = request.args.get("pwd", "")
    if not check_action_password(pwd):
        flash("Incorrect password. You cannot edit this driver.", "danger")
        return redirect(url_for("drivers"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM drivers WHERE id=?", (driver_id,))
    driver = cur.fetchone()
    if not driver:
        conn.close()
        flash("Driver not found.", "danger")
        return redirect(url_for("drivers"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Driver name is required.", "danger")
        else:
            try:
                cur.execute("UPDATE drivers SET name=? WHERE id=?", (name, driver_id))
                conn.commit()
                conn.close()
                flash("Driver updated successfully.", "success")
                return redirect(url_for("drivers"))
            except sqlite3.IntegrityError:
                flash("Another driver with this name already exists.", "danger")

    conn.close()
    return render_template("edit_driver.html", driver=driver)


def generate_pdf_report(entries, title, subtitle):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    logo_path = os.path.join("static", "images", "dd_logo.png")
    y = height - 40

    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 40, y - 40, width=80, height=40, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    # Centered company title and address
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y - 20, "DD Brothers Transport Inc.")

    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, y - 40, "190 Whithorn Cres, Caledonia, ON, N3W 0C9")
    c.drawCentredString(width / 2, y - 54, "ddbrotherstrans@gmail.com")
    c.drawCentredString(width / 2, y - 68, "437-985-0738, 437-219-0083")

    c.setLineWidth(1)
    c.setStrokeColor(colors.black)
    c.line(40, y - 80, width - 40, y - 80)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y - 100, title)
    c.setFont("Helvetica", 11)
    c.drawString(40, y - 116, subtitle)

    # 12-hour time with AM/PM
    c.drawRightString(width - 40, y - 100, datetime.now().strftime("Created on %Y-%m-%d %I:%M %p"))

    y_table = y - 140
    c.setFont("Helvetica-Bold", 10)
    headers = ["Date", "Truck", "Driver", "Main", "Type", "Amount", "HST", "Desc"]
    col_widths = [70, 50, 80, 45, 60, 55, 40, 120]
    x = 40
    for h, w in zip(headers, col_widths):
        c.drawString(x + 2, y_table, h)
        x += w
    c.line(40, y_table - 2, width - 40, y_table - 2)

    c.setFont("Helvetica", 9)
    y_table -= 14
    total_income = 0.0
    total_expense = 0.0

    for e in entries:
        if y_table < 60:
            c.showPage()
            y_table = height - 60
        x = 40

        amount_val = float(e["amount"])
        hst_val = 0.0
        if e["includes_hst"]:
            hst_val = amount_val * HST_RATE / (1 + HST_RATE)

        if e["main_category"] == "Income":
            total_income += amount_val
        else:
            total_expense += amount_val

        desc_text = e["description"] or ""
        short_desc = desc_text[:25] + ("..." if len(desc_text) > 25 else "")

        values = [
            e["date"],
            e["truck_number"],
            e["driver_name"],
            e["main_category"],
            e["sub_category"],
            f"${amount_val:,.2f}",
            f"${hst_val:,.2f}" if hst_val else "-",
            short_desc,
        ]

        for v, w in zip(values, col_widths):
            c.drawString(x + 2, y_table, str(v))
            x += w
        y_table -= 12

    y_table -= 10
    c.line(40, y_table, width - 40, y_table)
    y_table -= 14
    net = total_income - total_expense
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y_table, f"Total Income: ${total_income:,.2f}")
    y_table -= 14
    c.drawString(40, y_table, f"Total Expenses: ${total_expense:,.2f}")
    y_table -= 14
    c.setFillColor(colors.green if net >= 0 else colors.red)
    c.drawString(40, y_table, f"Net Income: ${net:,.2f}")
    c.setFillColor(colors.black)

    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(width / 2, 30, "Created by DD Manager")

    c.save()
    buffer.seek(0)
    return buffer


@app.route("/reports", methods=["GET", "POST"])
@login_required
def reports():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trucks ORDER BY number")
    trucks = cur.fetchall()

    entries = []
    selected_truck_id = None
    selected_month = None
    selected_year = None
    total_income = 0.0
    total_expense = 0.0
    net_income = 0.0

    if request.method == "POST":
        selected_truck_id = request.form.get("truck_id")
        selected_month = request.form.get("month")
        selected_year = request.form.get("year")

        if selected_truck_id and selected_month and selected_year:
            start_date = date(int(selected_year), int(selected_month), 1)
            if int(selected_month) == 12:
                end_date = date(int(selected_year) + 1, 1, 1)
            else:
                end_date = date(int(selected_year), int(selected_month) + 1, 1)

            cur.execute(
                """
                SELECT e.*, t.number AS truck_number, d.name AS driver_name
                FROM entries e
                JOIN trucks t ON e.truck_id = t.id
                JOIN drivers d ON e.driver_id = d.id
                WHERE e.truck_id=?
                  AND date(e.date) >= date(?) AND date(e.date) < date(?)
                ORDER BY date(e.date) ASC
                """,
                (int(selected_truck_id), start_date.isoformat(), end_date.isoformat()),
            )
            entries = cur.fetchall()

            total_income = sum(e["amount"] for e in entries if e["main_category"] == "Income")
            total_expense = sum(e["amount"] for e in entries if e["main_category"] == "Expense")
            net_income = total_income - total_expense

            if not entries:
                flash("No data found for this period.", "warning")
        else:
            flash("Please select truck, month and year.", "danger")

    conn.close()
    return render_template(
        "reports.html",
        trucks=trucks,
        entries=entries,
        selected_truck_id=selected_truck_id,
        selected_month=selected_month,
        selected_year=selected_year,
        total_income=total_income,
        total_expense=total_expense,
        net_income=net_income,
    )


@app.route("/reports/pdf")
@login_required
def reports_pdf():
    truck_id = request.args.get("truck_id")
    month = request.args.get("month")
    year = request.args.get("year")
    if not (truck_id and month and year):
        flash("Missing report parameters.", "danger")
        return redirect(url_for("reports"))

    conn = get_db_connection()
    cur = conn.cursor()

    start_date = date(int(year), int(month), 1)
    if int(month) == 12:
        end_date = date(int(year) + 1, 1, 1)
    else:
        end_date = date(int(year), int(month) + 1, 1)

    cur.execute(
        """
        SELECT e.*, t.number AS truck_number, d.name AS driver_name
        FROM entries e
        JOIN trucks t ON e.truck_id = t.id
        JOIN drivers d ON e.driver_id = d.id
        WHERE e.truck_id=?
          AND date(e.date) >= date(?) AND date(e.date) < date(?)
        ORDER BY date(e.date) ASC
        """,
        (int(truck_id), start_date.isoformat(), end_date.isoformat()),
    )
    entries = cur.fetchall()
    conn.close()

    if not entries:
        flash("No data found for this period.", "warning")
        return redirect(url_for("reports"))

    subtitle = f"Truck {truck_id} - {year}-{int(month):02d}"
    buffer = generate_pdf_report(entries, "Monthly Truck Report", subtitle)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"truck_report_{truck_id}_{year}_{month}.pdf",
        mimetype="application/pdf",
    )


@app.route("/driver-pay", methods=["GET", "POST"])
@login_required
def driver_pay():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM drivers ORDER BY name")
    drivers = cur.fetchall()

    entries = []
    selected_driver_id = None
    date_from = None
    date_to = None

    if request.method == "POST":
        selected_driver_id = request.form.get("driver_id")
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")

        if selected_driver_id and date_from and date_to:
            cur.execute(
                """
                SELECT e.*, t.number AS truck_number, d.name AS driver_name
                FROM entries e
                JOIN trucks t ON e.truck_id = t.id
                JOIN drivers d ON e.driver_id = d.id
                WHERE e.driver_id=?
                  AND e.main_category='Expense'
                  AND e.sub_category='Driver Pay'
                  AND date(e.date) >= date(?) AND date(e.date) <= date(?)
                ORDER BY date(e.date) ASC
                """,
                (int(selected_driver_id), date_from, date_to),
            )
            entries = cur.fetchall()
            if not entries:
                flash("No data found for this driver and period.", "warning")
        else:
            flash("Please select driver and date range.", "danger")

    conn.close()
    total = sum(e["amount"] for e in entries) if entries else 0.0

    return render_template(
        "driver_pay.html",
        drivers=drivers,
        entries=entries,
        selected_driver_id=selected_driver_id,
        date_from=date_from,
        date_to=date_to,
        total=total,
    )


@app.route("/driver-pay/pdf")
@login_required
def driver_pay_pdf():
    driver_id = request.args.get("driver_id")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    if not (driver_id and date_from and date_to):
        flash("Missing driver pay parameters.", "danger")
        return redirect(url_for("driver_pay"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT e.*, t.number AS truck_number, d.name AS driver_name
        FROM entries e
        JOIN trucks t ON e.truck_id = t.id
        JOIN drivers d ON e.driver_id = d.id
        WHERE e.driver_id=?
          AND e.main_category='Expense'
          AND e.sub_category='Driver Pay'
          AND date(e.date) >= date(?) AND date(e.date) <= date(?)
        ORDER BY date(e.date) ASC
        """,
        (int(driver_id), date_from, date_to),
    )
    entries = cur.fetchall()
    conn.close()

    if not entries:
        flash("No data found for this driver and period.", "warning")
        return redirect(url_for("driver_pay"))

    subtitle = f"Driver {driver_id} - {date_from} to {date_to}"
    buffer = generate_pdf_report(entries, "Driver Pay Report", subtitle)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"driver_pay_{driver_id}_{date_from}_{date_to}.pdf",
        mimetype="application/pdf",
    )


@app.route("/hst", methods=["GET", "POST"])
@login_required
def hst():
    conn = get_db_connection()
    cur = conn.cursor()

    hst_entries = []
    total_hst = 0.0
    date_from = None
    date_to = None

    if request.method == "POST":
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")

        if date_from and date_to:
            cur.execute(
                """
                SELECT e.*, t.number AS truck_number, d.name AS driver_name
                FROM entries e
                JOIN trucks t ON e.truck_id = t.id
                JOIN drivers d ON e.driver_id = d.id
                WHERE e.includes_hst=1
                  AND e.main_category='Expense'
                  AND date(e.date) >= date(?) AND date(e.date) <= date(?)
                ORDER BY date(e.date) ASC
                """,
                (date_from, date_to),
            )
            hst_entries = cur.fetchall()
            for e in hst_entries:
                amount = float(e["amount"])
                hst_component = amount * HST_RATE / (1 + HST_RATE)
                total_hst += hst_component
        else:
            flash("Please select date range.", "danger")

    conn.close()
    return render_template(
        "hst.html",
        hst_entries=hst_entries,
        total_hst=total_hst,
        date_from=date_from,
        date_to=date_to,
    )


@app.context_processor
def inject_now():
    return {"now": datetime.now()}


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
