import os
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from database import get_db, init_db, log_action
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

with app.app_context():
    init_db()


# ── Decorators ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'employee_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'Admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Auth ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'employee_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        # SQL: SELECT with JOIN to get employee and role in one query
        emp = db.execute("""
            SELECT e.*, r.role_name
            FROM   Employees e
            JOIN   Roles r ON e.role_id = r.role_id
            WHERE  e.username = ? AND e.is_active = 1
        """, (username,)).fetchone()
        db.close()
        if emp and check_password_hash(emp['password_hash'], password):
            session['employee_id'] = emp['employee_id']
            session['full_name']   = emp['full_name']
            session['role']        = emp['role_name']
            log_action(emp['employee_id'], 'Logged in', 'Employees', request.remote_addr)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    if 'employee_id' in session:
        log_action(session['employee_id'], 'Logged out', 'Employees', request.remote_addr)
    session.clear()
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
@login_required
@admin_required
def register():
    db = get_db()
    # SQL: SELECT all roles for dropdown
    roles = db.execute("SELECT * FROM Roles ORDER BY role_name").fetchall()
    if request.method == 'POST':
        username       = request.form['username'].strip()
        password       = request.form['password']
        full_name      = request.form['full_name'].strip()
        role_id        = request.form['role_id']
        license_number = request.form.get('license_number', '').strip()
        try:
            # SQL: INSERT new employee record
            db.execute("""
                INSERT INTO Employees
                    (role_id, username, password_hash, full_name, license_number, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (role_id, username, generate_password_hash(password),
                  full_name, license_number))
            db.commit()
            log_action(session['employee_id'],
                       f'Registered new employee: {username}',
                       'Employees', request.remote_addr)
            flash(f'Account for {full_name} created successfully.', 'success')
            return redirect(url_for('employees'))
        except Exception:
            flash('Username already exists. Choose a different one.', 'error')
    db.close()
    return render_template('register.html', roles=roles)


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()

    # SQL: COUNT aggregate functions
    total_products  = db.execute("SELECT COUNT(*) FROM Products").fetchone()[0]
    total_patients  = db.execute("SELECT COUNT(*) FROM Patients").fetchone()[0]
    total_employees = db.execute(
        "SELECT COUNT(*) FROM Employees WHERE is_active = 1").fetchone()[0]

    # SQL: SUM aggregate with WHERE date filter
    today_sales = db.execute("""
        SELECT COALESCE(SUM(net_amount), 0)
        FROM   Transactions
        WHERE  DATE(transaction_date) = DATE('now')
    """).fetchone()[0]

    # SQL: SELECT with multiple JOINs, ORDER BY, LIMIT
    recent_transactions = db.execute("""
        SELECT t.transaction_id, t.net_amount, t.transaction_date,
               COALESCE(p.first_name || ' ' || p.last_name, 'Walk-in') AS patient_name,
               e.full_name AS cashier
        FROM   Transactions t
        LEFT JOIN Patients  p ON t.patient_id  = p.patient_id
        JOIN      Employees e ON t.employee_id = e.employee_id
        ORDER BY  t.transaction_date DESC
        LIMIT 5
    """).fetchall()

    # SQL: JOIN with WHERE date range filter
    expiring_soon = db.execute("""
        SELECT p.product_name, pb.batch_number, pb.expiry_date, pb.current_stock
        FROM   Product_Batches pb
        JOIN   Products p ON pb.product_id = p.product_id
        WHERE  pb.expiry_date <= DATE('now', '+30 days')
          AND  pb.current_stock > 0
        ORDER BY pb.expiry_date ASC
    """).fetchall()

    # SQL: GROUP BY with HAVING to filter aggregated results
    low_stock = db.execute("""
        SELECT p.product_name, SUM(pb.current_stock) AS total_stock
        FROM   Product_Batches pb
        JOIN   Products p ON pb.product_id = p.product_id
        GROUP BY p.product_id
        HAVING total_stock < 50
        ORDER BY total_stock ASC
    """).fetchall()

    db.close()
    return render_template('dashboard.html',
                           total_products=total_products,
                           total_patients=total_patients,
                           total_employees=total_employees,
                           today_sales=today_sales,
                           recent_transactions=recent_transactions,
                           expiring_soon=expiring_soon,
                           low_stock=low_stock)


# ── Products ───────────────────────────────────────────────────────────────

@app.route('/products', methods=['GET', 'POST'])
@login_required
def products():
    db = get_db()
    search          = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')

    # SQL: SELECT with LEFT JOINs, LIKE search, GROUP BY, optional WHERE filter
    query = """
        SELECT p.*, c.name AS category_name,
               COALESCE(SUM(pb.current_stock), 0) AS total_stock
        FROM   Products p
        LEFT JOIN Categories      c  ON p.category_id = c.category_id
        LEFT JOIN Product_Batches pb ON p.product_id  = pb.product_id
        WHERE  (p.product_name LIKE ? OR p.generic_name LIKE ? OR p.sku_code LIKE ?)
    """
    params = [f'%{search}%', f'%{search}%', f'%{search}%']
    if category_filter:
        query += " AND p.category_id = ?"
        params.append(category_filter)
    query += " GROUP BY p.product_id ORDER BY p.product_name"

    prods      = db.execute(query, params).fetchall()
    categories = db.execute("SELECT * FROM Categories ORDER BY name").fetchall()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            # SQL: INSERT new product
            db.execute("""
                INSERT INTO Products
                    (category_id, sku_code, barcode, product_name,
                     generic_name, dosage_form, strength, is_prescription_only)
                VALUES (?,?,?,?,?,?,?,?)
            """, (request.form['category_id'], request.form.get('sku_code'),
                  request.form.get('barcode'),  request.form['product_name'],
                  request.form.get('generic_name'), request.form.get('dosage_form'),
                  request.form.get('strength'),
                  1 if request.form.get('is_prescription_only') else 0))
            db.commit()
            log_action(session['employee_id'],
                       f"Added product: {request.form['product_name']}",
                       'Products', request.remote_addr)
            flash('Product added successfully.', 'success')

        elif action == 'edit':
            pid = request.form['product_id']
            # SQL: UPDATE existing product
            db.execute("""
                UPDATE Products
                SET    category_id=?, product_name=?, generic_name=?,
                       dosage_form=?, strength=?, is_prescription_only=?
                WHERE  product_id=?
            """, (request.form['category_id'], request.form['product_name'],
                  request.form.get('generic_name'), request.form.get('dosage_form'),
                  request.form.get('strength'),
                  1 if request.form.get('is_prescription_only') else 0, pid))
            db.commit()
            log_action(session['employee_id'], f'Updated product ID {pid}',
                       'Products', request.remote_addr)
            flash('Product updated.', 'success')

        elif action == 'delete':
            pid = request.form['product_id']
            # SQL: DELETE record
            db.execute("DELETE FROM Products WHERE product_id=?", (pid,))
            db.commit()
            log_action(session['employee_id'], f'Deleted product ID {pid}',
                       'Products', request.remote_addr)
            flash('Product deleted.', 'success')

        elif action == 'add_batch':
            # SQL: INSERT batch; also record price history
            pid       = request.form['product_id']
            new_price = float(request.form['selling_price'])
            db.execute("""
                INSERT INTO Product_Batches
                    (product_id, batch_number, mfg_date, expiry_date,
                     cost_price, selling_price, current_stock)
                VALUES (?,?,?,?,?,?,?)
            """, (pid, request.form['batch_number'], request.form.get('mfg_date'),
                  request.form['expiry_date'], float(request.form['cost_price']),
                  new_price, int(request.form['stock'])))
            # SQL: INSERT price history record
            db.execute("""
                INSERT INTO Price_History (product_id, old_price, new_price)
                VALUES (?, 0, ?)
            """, (pid, new_price))
            db.commit()
            log_action(session['employee_id'], f'Added batch for product {pid}',
                       'Product_Batches', request.remote_addr)
            flash('Batch added successfully.', 'success')

        db.close()
        return redirect(url_for('products'))

    db.close()
    return render_template('products.html', products=prods,
                           categories=categories, search=search,
                           category_filter=category_filter)


# ── Patients ───────────────────────────────────────────────────────────────

@app.route('/patients', methods=['GET', 'POST'])
@login_required
def patients():
    db     = get_db()
    search = request.args.get('search', '').strip()

    # SQL: SELECT with LIKE on multiple columns using OR
    pts = db.execute("""
        SELECT * FROM Patients
        WHERE  first_name LIKE ? OR last_name LIKE ? OR phone LIKE ?
        ORDER BY last_name, first_name
    """, (f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            # SQL: INSERT patient
            db.execute("""
                INSERT INTO Patients
                    (first_name, last_name, dob, gender, phone, medical_history, allergies)
                VALUES (?,?,?,?,?,?,?)
            """, (request.form['first_name'], request.form['last_name'],
                  request.form.get('dob'), request.form.get('gender'),
                  request.form.get('phone'), request.form.get('medical_history'),
                  request.form.get('allergies')))
            db.commit()
            log_action(session['employee_id'],
                       f"Added patient: {request.form['first_name']} {request.form['last_name']}",
                       'Patients', request.remote_addr)
            flash('Patient added successfully.', 'success')

        elif action == 'edit':
            pid = request.form['patient_id']
            # SQL: UPDATE patient record
            db.execute("""
                UPDATE Patients
                SET    first_name=?, last_name=?, dob=?, gender=?,
                       phone=?, medical_history=?, allergies=?
                WHERE  patient_id=?
            """, (request.form['first_name'], request.form['last_name'],
                  request.form.get('dob'), request.form.get('gender'),
                  request.form.get('phone'), request.form.get('medical_history'),
                  request.form.get('allergies'), pid))
            db.commit()
            log_action(session['employee_id'], f'Updated patient ID {pid}',
                       'Patients', request.remote_addr)
            flash('Patient record updated.', 'success')

        db.close()
        return redirect(url_for('patients'))

    db.close()
    return render_template('patients.html', patients=pts, search=search)


# ── Prescriptions ──────────────────────────────────────────────────────────

@app.route('/prescriptions', methods=['GET', 'POST'])
@login_required
def prescriptions():
    db = get_db()

    # SQL: SELECT with multiple JOINs
    rxs = db.execute("""
        SELECT rx.*,
               p.first_name || ' ' || p.last_name AS patient_name,
               pr.name AS prescriber_name
        FROM   Prescriptions rx
        JOIN      Patients   p  ON rx.patient_id    = p.patient_id
        LEFT JOIN Prescribers pr ON rx.prescriber_id = pr.prescriber_id
        ORDER BY rx.date_issued DESC
    """).fetchall()

    patients    = db.execute("SELECT * FROM Patients    ORDER BY last_name").fetchall()
    prescribers = db.execute("SELECT * FROM Prescribers ORDER BY name").fetchall()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            # SQL: INSERT prescription
            db.execute("""
                INSERT INTO Prescriptions
                    (patient_id, prescriber_id, date_issued, expiry_date, is_verified)
                VALUES (?,?,?,?,0)
            """, (request.form['patient_id'],
                  request.form.get('prescriber_id') or None,
                  request.form['date_issued'],
                  request.form.get('expiry_date') or None))
            db.commit()
            log_action(session['employee_id'], 'Added prescription',
                       'Prescriptions', request.remote_addr)
            flash('Prescription added.', 'success')

        elif action == 'verify':
            rxid = request.form['prescription_id']
            # SQL: UPDATE single boolean field
            db.execute("""
                UPDATE Prescriptions SET is_verified = 1 WHERE prescription_id = ?
            """, (rxid,))
            db.commit()
            log_action(session['employee_id'],
                       f'Verified prescription ID {rxid}',
                       'Prescriptions', request.remote_addr)
            flash('Prescription verified.', 'success')

        db.close()
        return redirect(url_for('prescriptions'))

    db.close()
    return render_template('prescriptions.html', prescriptions=rxs,
                           patients=patients, prescribers=prescribers)


# ── Transactions ───────────────────────────────────────────────────────────

@app.route('/transactions', methods=['GET', 'POST'])
@login_required
def transactions():
    db = get_db()

    # SQL: SELECT with LEFT JOIN and JOIN, ORDER BY, LIMIT
    txns = db.execute("""
        SELECT t.*, e.full_name AS cashier,
               COALESCE(p.first_name || ' ' || p.last_name, 'Walk-in') AS patient_name
        FROM   Transactions t
        JOIN      Employees e ON t.employee_id = e.employee_id
        LEFT JOIN Patients  p ON t.patient_id  = p.patient_id
        ORDER BY  t.transaction_date DESC
        LIMIT 100
    """).fetchall()

    patients = db.execute("SELECT * FROM Patients ORDER BY last_name").fetchall()

    # SQL: SELECT with JOIN and WHERE filtering available stock and non-expired
    batches = db.execute("""
        SELECT pb.batch_id, p.product_name, pb.batch_number,
               pb.selling_price, pb.current_stock, pb.expiry_date
        FROM   Product_Batches pb
        JOIN   Products p ON pb.product_id = p.product_id
        WHERE  pb.current_stock > 0 AND pb.expiry_date >= DATE('now')
        ORDER BY p.product_name
    """).fetchall()

    if request.method == 'POST':
        patient_id = request.form.get('patient_id') or None
        discount   = float(request.form.get('discount', 0))
        batch_ids  = request.form.getlist('batch_id[]')
        quantities = request.form.getlist('quantity[]')

        if not batch_ids:
            flash('Please add at least one item to the sale.', 'error')
            db.close()
            return redirect(url_for('transactions'))

        try:
            total = 0.0
            items = []
            for bid, qty in zip(batch_ids, quantities):
                qty   = int(qty)
                # SQL: SELECT batch to check stock
                batch = db.execute(
                    "SELECT * FROM Product_Batches WHERE batch_id=?", (bid,)
                ).fetchone()
                if not batch or batch['current_stock'] < qty:
                    flash(f'Insufficient stock for selected batch.', 'error')
                    db.close()
                    return redirect(url_for('transactions'))
                total += batch['selling_price'] * qty
                items.append((bid, qty, batch['selling_price'], batch['product_id']))

            tax = round(total * 0.16, 2)
            net = round(total + tax - discount, 2)

            # SQL: INSERT main transaction record
            cur = db.execute("""
                INSERT INTO Transactions
                    (patient_id, employee_id, total_amount, tax_amount,
                     discount_amount, net_amount)
                VALUES (?,?,?,?,?,?)
            """, (patient_id, session['employee_id'], total, tax, discount, net))
            txn_id = cur.lastrowid

            for bid, qty, price, _ in items:
                # SQL: INSERT line items
                db.execute("""
                    INSERT INTO Transaction_Items
                        (transaction_id, batch_id, quantity, unit_price)
                    VALUES (?,?,?,?)
                """, (txn_id, bid, qty, price))
                # SQL: UPDATE stock quantity
                db.execute("""
                    UPDATE Product_Batches
                    SET    current_stock = current_stock - ?
                    WHERE  batch_id = ?
                """, (qty, bid))

            db.commit()
            log_action(session['employee_id'],
                       f'Processed sale TXN-{txn_id} net={net:.2f}',
                       'Transactions', request.remote_addr)
            flash(f'Sale TXN-{txn_id} completed. Net: ${net:.2f}', 'success')

        except Exception as e:
            db.rollback()
            flash(f'Sale failed: {str(e)}', 'error')

        db.close()
        return redirect(url_for('transactions'))

    db.close()
    return render_template('transactions.html', transactions=txns,
                           patients=patients, batches=batches)


# ── Sales Returns ──────────────────────────────────────────────────────────

@app.route('/returns', methods=['GET', 'POST'])
@login_required
def returns():
    db = get_db()
    # SQL: SELECT with JOIN
    all_returns = db.execute("""
        SELECT sr.*, t.net_amount AS original_amount,
               e.full_name AS processed_by
        FROM   Sales_Returns sr
        JOIN   Transactions t ON sr.transaction_id = t.transaction_id
        JOIN   Employees    e ON sr.employee_id    = e.employee_id
        ORDER BY sr.return_date DESC
    """).fetchall()

    # SQL: SELECT transactions for dropdown
    txns = db.execute("""
        SELECT transaction_id, net_amount, transaction_date FROM Transactions
        ORDER BY transaction_date DESC LIMIT 50
    """).fetchall()

    if request.method == 'POST':
        txn_id   = request.form['transaction_id']
        reason   = request.form.get('reason', '')
        refund   = float(request.form.get('refund_amount', 0))
        # SQL: INSERT return record
        db.execute("""
            INSERT INTO Sales_Returns
                (transaction_id, employee_id, reason, refund_amount)
            VALUES (?,?,?,?)
        """, (txn_id, session['employee_id'], reason, refund))
        db.commit()
        log_action(session['employee_id'],
                   f'Processed return for TXN-{txn_id}',
                   'Sales_Returns', request.remote_addr)
        flash('Return processed successfully.', 'success')
        db.close()
        return redirect(url_for('returns'))

    db.close()
    return render_template('returns.html', returns=all_returns, transactions=txns)


# ── Purchase Orders ────────────────────────────────────────────────────────

@app.route('/purchase_orders', methods=['GET', 'POST'])
@login_required
def purchase_orders():
    db = get_db()

    # SQL: SELECT with JOINs
    pos = db.execute("""
        SELECT po.*, s.company_name, e.full_name AS ordered_by
        FROM   Purchase_Orders po
        JOIN   Suppliers  s ON po.supplier_id = s.supplier_id
        JOIN   Employees  e ON po.employee_id = e.employee_id
        ORDER BY po.order_date DESC
    """).fetchall()

    suppliers = db.execute("SELECT * FROM Suppliers ORDER BY company_name").fetchall()
    products  = db.execute(
        "SELECT product_id, product_name, sku_code FROM Products ORDER BY product_name"
    ).fetchall()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            supplier_id = request.form['supplier_id']
            # SQL: INSERT purchase order header
            cur = db.execute("""
                INSERT INTO Purchase_Orders (supplier_id, employee_id, status)
                VALUES (?, ?, 'Pending')
            """, (supplier_id, session['employee_id']))
            po_id = cur.lastrowid

            product_ids = request.form.getlist('product_id[]')
            quantities  = request.form.getlist('quantity[]')
            unit_costs  = request.form.getlist('unit_cost[]')
            total = 0.0
            for pid, qty, cost in zip(product_ids, quantities, unit_costs):
                qty  = int(qty)
                cost = float(cost)
                # SQL: INSERT PO line items
                db.execute("""
                    INSERT INTO PO_Items (po_id, product_id, quantity_ordered, unit_cost)
                    VALUES (?,?,?,?)
                """, (po_id, pid, qty, cost))
                total += qty * cost
            # SQL: UPDATE total cost
            db.execute("UPDATE Purchase_Orders SET total_cost=? WHERE po_id=?",
                       (total, po_id))
            db.commit()
            log_action(session['employee_id'], f'Created PO #{po_id}',
                       'Purchase_Orders', request.remote_addr)
            flash(f'Purchase Order #{po_id} created. Total: ${total:.2f}', 'success')

        elif action == 'receive':
            po_id = request.form['po_id']
            # SQL: SELECT PO items to process
            items = db.execute(
                "SELECT * FROM PO_Items WHERE po_id=?", (po_id,)
            ).fetchall()
            for item in items:
                # SQL: INSERT new batch for each received item
                db.execute("""
                    INSERT INTO Product_Batches
                        (product_id, cost_price, selling_price, current_stock)
                    VALUES (?,?,?,?)
                """, (item['product_id'], item['unit_cost'],
                      round(item['unit_cost'] * 1.4, 2),
                      item['quantity_ordered']))
            # SQL: UPDATE PO status
            db.execute("""
                UPDATE Purchase_Orders SET status='Received' WHERE po_id=?
            """, (po_id,))
            db.commit()
            log_action(session['employee_id'],
                       f'Received PO #{po_id} — stock updated',
                       'Purchase_Orders', request.remote_addr)
            flash(f'PO #{po_id} received and stock updated.', 'success')

        elif action == 'cancel':
            po_id = request.form['po_id']
            # SQL: UPDATE status to Cancelled
            db.execute("""
                UPDATE Purchase_Orders SET status='Cancelled' WHERE po_id=?
            """, (po_id,))
            db.commit()
            log_action(session['employee_id'], f'Cancelled PO #{po_id}',
                       'Purchase_Orders', request.remote_addr)
            flash(f'PO #{po_id} cancelled.', 'success')

        db.close()
        return redirect(url_for('purchase_orders'))

    db.close()
    return render_template('purchase_orders.html', purchase_orders=pos,
                           suppliers=suppliers, products=products)


# ── Inventory ──────────────────────────────────────────────────────────────

@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    db = get_db()

    # SQL: SELECT with JOIN across 3 tables
    inv = db.execute("""
        SELECT pb.batch_id, pb.batch_number, pb.expiry_date,
               pb.cost_price, pb.selling_price, pb.current_stock,
               p.product_id, p.product_name, p.sku_code,
               c.name AS category
        FROM   Product_Batches pb
        JOIN   Products    p ON pb.product_id  = p.product_id
        LEFT JOIN Categories c ON p.category_id = c.category_id
        ORDER BY p.product_name, pb.expiry_date
    """).fetchall()

    # SQL: SELECT adjustment history with JOIN
    adjustments = db.execute("""
        SELECT ia.*, p.product_name, e.full_name AS adjusted_by,
               pb.batch_number
        FROM   Inventory_Adjustments ia
        JOIN   Products        p  ON ia.product_id = p.product_id
        JOIN   Employees       e  ON ia.employee_id = e.employee_id
        JOIN   Product_Batches pb ON ia.batch_id    = pb.batch_id
        ORDER BY ia.adjustment_date DESC
        LIMIT 30
    """).fetchall()

    if request.method == 'POST':
        batch_id = request.form['batch_id']
        adj_type = request.form['adjustment_type']
        qty      = int(request.form['quantity'])
        notes    = request.form.get('notes', '')

        # SQL: SELECT batch to validate
        batch = db.execute(
            "SELECT * FROM Product_Batches WHERE batch_id=?", (batch_id,)
        ).fetchone()

        new_stock = (batch['current_stock'] + qty
                     if adj_type == 'Addition'
                     else batch['current_stock'] - qty)

        if new_stock < 0:
            flash('Adjustment would result in negative stock.', 'error')
        else:
            # SQL: UPDATE batch stock
            db.execute("""
                UPDATE Product_Batches SET current_stock=? WHERE batch_id=?
            """, (new_stock, batch_id))
            # SQL: INSERT adjustment record
            db.execute("""
                INSERT INTO Inventory_Adjustments
                    (product_id, batch_id, employee_id,
                     adjustment_type, quantity_adjusted, notes)
                VALUES (?,?,?,?,?,?)
            """, (batch['product_id'], batch_id, session['employee_id'],
                  adj_type, qty, notes))
            db.commit()
            log_action(session['employee_id'],
                       f'{adj_type} of {qty} units on batch {batch_id}',
                       'Inventory_Adjustments', request.remote_addr)
            flash('Inventory adjusted successfully.', 'success')

        db.close()
        return redirect(url_for('inventory'))

    db.close()
    return render_template('inventory.html', inventory=inv, adjustments=adjustments)


# ── Reports ────────────────────────────────────────────────────────────────

@app.route('/reports')
@login_required
def reports():
    db = get_db()

    # SQL: GROUP BY date with COUNT and SUM aggregates
    daily_sales = db.execute("""
        SELECT DATE(transaction_date) AS sale_date,
               COUNT(*)               AS total_txns,
               SUM(net_amount)        AS total_revenue
        FROM   Transactions
        GROUP BY DATE(transaction_date)
        ORDER BY sale_date DESC
        LIMIT 30
    """).fetchall()

    # SQL: JOIN across 4 tables with GROUP BY category
    sales_by_category = db.execute("""
        SELECT c.name AS category,
               COUNT(DISTINCT t.transaction_id)       AS txn_count,
               SUM(ti.quantity * ti.unit_price)       AS revenue
        FROM   Transaction_Items ti
        JOIN   Product_Batches pb ON ti.batch_id       = pb.batch_id
        JOIN   Products        p  ON pb.product_id     = p.product_id
        JOIN   Categories      c  ON p.category_id     = c.category_id
        JOIN   Transactions    t  ON ti.transaction_id = t.transaction_id
        GROUP BY c.category_id
        ORDER BY revenue DESC
    """).fetchall()

    # SQL: Subquery-style aggregation — top selling products
    top_products = db.execute("""
        SELECT p.product_name,
               SUM(ti.quantity)               AS units_sold,
               SUM(ti.quantity * ti.unit_price) AS revenue
        FROM   Transaction_Items ti
        JOIN   Product_Batches pb ON ti.batch_id   = pb.batch_id
        JOIN   Products        p  ON pb.product_id = p.product_id
        GROUP BY p.product_id
        ORDER BY units_sold DESC
        LIMIT 10
    """).fetchall()

    # SQL: HAVING clause to filter aggregated groups
    low_stock = db.execute("""
        SELECT p.product_name, SUM(pb.current_stock) AS stock
        FROM   Product_Batches pb
        JOIN   Products p ON pb.product_id = p.product_id
        GROUP BY p.product_id
        HAVING stock < 50
        ORDER BY stock ASC
    """).fetchall()

    # SQL: WHERE with BETWEEN date range
    expiring = db.execute("""
        SELECT p.product_name, pb.batch_number, pb.expiry_date, pb.current_stock
        FROM   Product_Batches pb
        JOIN   Products p ON pb.product_id = p.product_id
        WHERE  pb.expiry_date BETWEEN DATE('now') AND DATE('now', '+60 days')
          AND  pb.current_stock > 0
        ORDER BY pb.expiry_date ASC
    """).fetchall()

    # SQL: AVG aggregate function
    avg_sale = db.execute(
        "SELECT ROUND(AVG(net_amount), 2) FROM Transactions"
    ).fetchone()[0] or 0

    # SQL: MAX and MIN aggregates
    max_sale = db.execute(
        "SELECT ROUND(MAX(net_amount), 2) FROM Transactions"
    ).fetchone()[0] or 0

    # SQL: COUNT with GROUP BY employee — top performing staff
    top_staff = db.execute("""
        SELECT e.full_name,
               COUNT(t.transaction_id) AS sales_count,
               SUM(t.net_amount)       AS total_sales
        FROM   Transactions t
        JOIN   Employees    e ON t.employee_id = e.employee_id
        GROUP BY t.employee_id
        ORDER BY total_sales DESC
        LIMIT 5
    """).fetchall()

    db.close()
    return render_template('reports.html',
                           daily_sales=daily_sales,
                           sales_by_category=sales_by_category,
                           top_products=top_products,
                           low_stock=low_stock,
                           expiring=expiring,
                           avg_sale=avg_sale,
                           max_sale=max_sale,
                           top_staff=top_staff)


# ── Employees ──────────────────────────────────────────────────────────────

@app.route('/employees', methods=['GET', 'POST'])
@login_required
@admin_required
def employees():
    db = get_db()

    # SQL: SELECT with JOIN
    emps  = db.execute("""
        SELECT e.*, r.role_name FROM Employees e
        JOIN   Roles r ON e.role_id = r.role_id
        ORDER BY e.full_name
    """).fetchall()
    roles = db.execute("SELECT * FROM Roles ORDER BY role_name").fetchall()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'toggle':
            eid = request.form['employee_id']
            # SQL: UPDATE using NOT to flip boolean value
            db.execute("""
                UPDATE Employees SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END
                WHERE  employee_id=?
            """, (eid,))
            db.commit()
            log_action(session['employee_id'],
                       f'Toggled active status for employee {eid}',
                       'Employees', request.remote_addr)
            flash('Employee status updated.', 'success')

        elif action == 'change_role':
            eid     = request.form['employee_id']
            role_id = request.form['role_id']
            # SQL: UPDATE role
            db.execute("UPDATE Employees SET role_id=? WHERE employee_id=?",
                       (role_id, eid))
            db.commit()
            log_action(session['employee_id'],
                       f'Changed role for employee {eid}',
                       'Employees', request.remote_addr)
            flash('Role updated.', 'success')

        db.close()
        return redirect(url_for('employees'))

    db.close()
    return render_template('employees.html', employees=emps, roles=roles)


# ── Audit Logs ─────────────────────────────────────────────────────────────

@app.route('/audit_logs')
@login_required
@admin_required
def audit_logs():
    db           = get_db()
    table_filter = request.args.get('table', '')

    # SQL: LEFT JOIN with optional WHERE filter, ORDER BY, LIMIT
    query  = """
        SELECT al.*, COALESCE(e.full_name, 'System') AS employee_name
        FROM   Audit_Logs al
        LEFT JOIN Employees e ON al.employee_id = e.employee_id
    """
    params = []
    if table_filter:
        query += " WHERE al.table_affected = ?"
        params.append(table_filter)
    query += " ORDER BY al.timestamp DESC LIMIT 200"

    logs = db.execute(query, params).fetchall()

    # SQL: DISTINCT to get unique table names for filter dropdown
    tables = db.execute("""
        SELECT DISTINCT table_affected FROM Audit_Logs
        WHERE  table_affected IS NOT NULL
        ORDER BY table_affected
    """).fetchall()

    db.close()
    return render_template('audit_logs.html', logs=logs,
                           tables=tables, table_filter=table_filter)


if __name__ == '__main__':
    app.run(debug=True)
