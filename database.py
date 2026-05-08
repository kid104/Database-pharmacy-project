import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get('DB_PATH', 'pharmacy.db')

os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS Roles (
            role_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name        TEXT NOT NULL UNIQUE,
            permissions_json TEXT
        );

        CREATE TABLE IF NOT EXISTS Employees (
            employee_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id        INTEGER NOT NULL,
            username       TEXT NOT NULL UNIQUE,
            password_hash  TEXT NOT NULL,
            full_name      TEXT NOT NULL,
            license_number TEXT,
            is_active      INTEGER DEFAULT 1,
            FOREIGN KEY (role_id) REFERENCES Roles(role_id)
        );

        CREATE TABLE IF NOT EXISTS Categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS Suppliers (
            supplier_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name   TEXT NOT NULL,
            contact_person TEXT,
            phone          TEXT,
            email          TEXT,
            address        TEXT
        );

        CREATE TABLE IF NOT EXISTS Pharmacy_Settings (
            setting_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            pharmacy_name TEXT NOT NULL,
            tax_number    TEXT,
            address       TEXT,
            currency      TEXT DEFAULT 'USD'
        );

        CREATE TABLE IF NOT EXISTS Products (
            product_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id          INTEGER,
            sku_code             TEXT UNIQUE,
            barcode              TEXT,
            product_name         TEXT NOT NULL,
            generic_name         TEXT,
            dosage_form          TEXT,
            strength             TEXT,
            is_prescription_only INTEGER DEFAULT 0,
            FOREIGN KEY (category_id) REFERENCES Categories(category_id)
        );

        CREATE TABLE IF NOT EXISTS Product_Batches (
            batch_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id    INTEGER NOT NULL,
            batch_number  TEXT,
            mfg_date      DATE,
            expiry_date   DATE,
            cost_price    REAL,
            selling_price REAL,
            current_stock INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES Products(product_id)
        );

        CREATE TABLE IF NOT EXISTS Price_History (
            price_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL,
            old_price   REAL,
            new_price   REAL,
            change_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products(product_id)
        );

        CREATE TABLE IF NOT EXISTS Patients (
            patient_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name      TEXT NOT NULL,
            last_name       TEXT NOT NULL,
            dob             DATE,
            gender          TEXT,
            phone           TEXT,
            medical_history TEXT,
            allergies       TEXT
        );

        CREATE TABLE IF NOT EXISTS Prescribers (
            prescriber_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL,
            license_number TEXT,
            clinic_name    TEXT,
            phone          TEXT
        );

        CREATE TABLE IF NOT EXISTS Prescriptions (
            prescription_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id      INTEGER NOT NULL,
            prescriber_id   INTEGER,
            date_issued     DATE,
            expiry_date     DATE,
            is_verified     INTEGER DEFAULT 0,
            FOREIGN KEY (patient_id)    REFERENCES Patients(patient_id),
            FOREIGN KEY (prescriber_id) REFERENCES Prescribers(prescriber_id)
        );

        CREATE TABLE IF NOT EXISTS Purchase_Orders (
            po_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            order_date  DATE    DEFAULT CURRENT_DATE,
            total_cost  REAL    DEFAULT 0,
            status      TEXT    DEFAULT 'Pending',
            FOREIGN KEY (supplier_id) REFERENCES Suppliers(supplier_id),
            FOREIGN KEY (employee_id) REFERENCES Employees(employee_id)
        );

        CREATE TABLE IF NOT EXISTS PO_Items (
            po_item_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id            INTEGER NOT NULL,
            product_id       INTEGER NOT NULL,
            quantity_ordered INTEGER NOT NULL,
            unit_cost        REAL    NOT NULL,
            FOREIGN KEY (po_id)      REFERENCES Purchase_Orders(po_id),
            FOREIGN KEY (product_id) REFERENCES Products(product_id)
        );

        CREATE TABLE IF NOT EXISTS Transactions (
            transaction_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id       INTEGER,
            employee_id      INTEGER NOT NULL,
            prescription_id  INTEGER,
            total_amount     REAL DEFAULT 0,
            tax_amount       REAL DEFAULT 0,
            discount_amount  REAL DEFAULT 0,
            net_amount       REAL DEFAULT 0,
            transaction_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id)  REFERENCES Patients(patient_id),
            FOREIGN KEY (employee_id) REFERENCES Employees(employee_id)
        );

        CREATE TABLE IF NOT EXISTS Transaction_Items (
            item_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            batch_id       INTEGER NOT NULL,
            quantity       INTEGER NOT NULL,
            unit_price     REAL NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES Transactions(transaction_id),
            FOREIGN KEY (batch_id)       REFERENCES Product_Batches(batch_id)
        );

        CREATE TABLE IF NOT EXISTS Inventory_Adjustments (
            adjustment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id        INTEGER NOT NULL,
            batch_id          INTEGER NOT NULL,
            employee_id       INTEGER NOT NULL,
            adjustment_type   TEXT NOT NULL,
            quantity_adjusted INTEGER NOT NULL,
            adjustment_date   DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes             TEXT,
            FOREIGN KEY (product_id)  REFERENCES Products(product_id),
            FOREIGN KEY (batch_id)    REFERENCES Product_Batches(batch_id),
            FOREIGN KEY (employee_id) REFERENCES Employees(employee_id)
        );

        CREATE TABLE IF NOT EXISTS Sales_Returns (
            return_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            employee_id    INTEGER NOT NULL,
            return_date    DATETIME DEFAULT CURRENT_TIMESTAMP,
            reason         TEXT,
            refund_amount  REAL,
            FOREIGN KEY (transaction_id) REFERENCES Transactions(transaction_id),
            FOREIGN KEY (employee_id)    REFERENCES Employees(employee_id)
        );

        CREATE TABLE IF NOT EXISTS Audit_Logs (
            log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id      INTEGER,
            action_performed TEXT NOT NULL,
            table_affected   TEXT,
            timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
            ip_address       TEXT,
            FOREIGN KEY (employee_id) REFERENCES Employees(employee_id)
        );
    ''')

    if c.execute("SELECT COUNT(*) FROM Roles").fetchone()[0] == 0:
        c.executescript('''
            INSERT INTO Roles (role_name, permissions_json) VALUES
                ('Admin',      '{"all": true}'),
                ('Pharmacist', '{"sales": true, "inventory": true}'),
                ('Cashier',    '{"sales": true}');

            INSERT INTO Pharmacy_Settings (pharmacy_name, tax_number, address, currency)
            VALUES ('City Pharmacy', 'TAX-12345', '123 Main Street, Cityville', 'USD');

            INSERT INTO Categories (name, description) VALUES
                ('Antibiotics',    'Antibiotic medications'),
                ('Analgesics',     'Pain relief medications'),
                ('Vitamins',       'Vitamins and supplements'),
                ('Antidiabetics',  'Diabetes management drugs'),
                ('Cardiovascular', 'Heart and blood pressure drugs');

            INSERT INTO Suppliers (company_name, contact_person, phone, email, address) VALUES
                ('MediSupply Co',  'John Smith', '555-0100', 'john@medisupply.com',  '10 Supply Road'),
                ('PharmaDist Ltd', 'Sarah Lee',  '555-0200', 'sarah@pharmadist.com', '20 Dist Avenue');

            INSERT INTO Products (category_id, sku_code, product_name, generic_name, dosage_form, strength, is_prescription_only) VALUES
                (1, 'AMX-500', 'Amoxicillin', 'Amoxicillin',   'Capsule', '500mg', 1),
                (2, 'PCM-500', 'Paracetamol', 'Acetaminophen', 'Tablet',  '500mg', 0),
                (3, 'VTC-500', 'Vitamin C',   'Ascorbic Acid', 'Tablet',  '500mg', 0),
                (4, 'MET-500', 'Metformin',   'Metformin HCl', 'Tablet',  '500mg', 1),
                (5, 'ATN-050', 'Atenolol',    'Atenolol',      'Tablet',  '50mg',  1);

            INSERT INTO Product_Batches (product_id, batch_number, mfg_date, expiry_date, cost_price, selling_price, current_stock) VALUES
                (1, 'AMX-2024-001', '2024-01-01', '2026-01-01', 0.50, 1.20, 200),
                (2, 'PCM-2024-001', '2024-01-01', '2026-06-01', 0.10, 0.50, 500),
                (3, 'VTC-2024-001', '2024-01-01', '2025-12-01', 0.20, 0.80, 300),
                (4, 'MET-2024-001', '2024-02-01', '2026-02-01', 0.30, 0.90, 150),
                (5, 'ATN-2024-001', '2024-03-01', '2026-03-01', 0.40, 1.00,  40);

            INSERT INTO Patients (first_name, last_name, dob, gender, phone, medical_history, allergies) VALUES
                ('James', 'Wilson',  '1985-03-15', 'Male',   '555-1001', 'Hypertension',   'Penicillin'),
                ('Mary',  'Johnson', '1990-07-22', 'Female', '555-1002', 'Diabetes Type 2','None'),
                ('David', 'Brown',   '1978-11-05', 'Male',   '555-1003', 'Asthma',         'Aspirin');

            INSERT INTO Prescribers (name, license_number, clinic_name, phone) VALUES
                ('Dr. Alice Mwangi', 'LIC-1001', 'City Medical Centre', '555-2001'),
                ('Dr. Bob Kariuki',  'LIC-1002', 'Westside Clinic',     '555-2002');
        ''')
        conn.execute("""
            INSERT INTO Employees (role_id, username, password_hash, full_name, is_active)
            VALUES (1, 'admin', ?, 'System Administrator', 1)
        """, (generate_password_hash('admin123'),))

    conn.commit()
    conn.close()


def log_action(employee_id, action, table, ip=''):
    conn = get_db()
    conn.execute("""
        INSERT INTO Audit_Logs (employee_id, action_performed, table_affected, ip_address)
        VALUES (?, ?, ?, ?)
    """, (employee_id, action, table, ip))
    conn.commit()
    conn.close()
