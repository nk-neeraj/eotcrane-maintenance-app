import sqlite3
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import string
import requests
import base64
import streamlit as st
import os

DB_NAME = "cmms.db"
JSON_KEY = 'plantmaintence-d2bfc889466e.json'

try:
    SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "")
    WEBHOOK_URL = st.secrets.get("WEBHOOK_URL", "")
    INITIAL_ADMIN_PASSWORD = st.secrets.get("INITIAL_ADMIN_PASSWORD")
except Exception:
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD")

# Google Sheets Setup
scopes = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def upload_image_to_drive(uploaded_file):
    try:
        file_bytes = uploaded_file.getvalue()
        encoded_data = base64.b64encode(file_bytes).decode('utf-8')
        payload = {
            'fileData': encoded_data,
            'mimeType': uploaded_file.type,
            'fileName': uploaded_file.name
        }
        response = requests.post(WEBHOOK_URL, data=payload)
        
        try:
            result = response.json()
            if result.get('status') == 'success':
                # Return a formatted string that we can split later or just the URL
                # Since we want to display the filename in the link but keep the link,
                # LinkColumn doesn't easily support per-row display text from the same column.
                # But we can store it as "FILENAME|URL" and process it.
                # However, that breaks the "LinkColumn" unless we pre-process.
                return f"{uploaded_file.name}|{result.get('url')}"
        except:
            pass
            
        return uploaded_file.name
    except Exception as e:
        print(f"Error uploading image: {e}")
        return uploaded_file.name

def get_gsheets_client():
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            # If deploying on Streamlit Cloud, use secrets
            creds_dict = st.secrets["gcp_service_account"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass
        
    # Fallback to local JSON file for local testing
    creds = Credentials.from_service_account_file(JSON_KEY, scopes=scopes)
    return gspread.authorize(creds)

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def push_table_to_gsheets(table_name):
    """Pushes a table from local SQLite to Google Sheets"""
    try:
        conn = get_connection()
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        conn.close()
        
        client = get_gsheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID)
        try:
            ws = sheet.worksheet(table_name)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title=table_name, rows=str(max(100, len(df) + 10)), cols=str(max(20, len(df.columns) + 5)))
        
        if not df.empty:
            date_cols = ['last_maintenance_date', 'next_due_date', 'date', 'last_replacement_date']
            datetime_cols = ['taking_over_datetime', 'handing_over_datetime', 'breakdown_reported_datetime']
            
            for col in date_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce', format='mixed').dt.strftime('%m/%d/%Y').fillna('')
            for col in datetime_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce', format='mixed').dt.strftime('%m/%d/%Y %H:%M:%S').fillna('')
                    
            df = df.fillna('')
            data = [df.columns.values.tolist()] + df.values.tolist()
            ws.update(range_name='A1', values=data)
        else:
            ws.update(range_name='A1', values=[df.columns.values.tolist()])
    except Exception as e:
        print(f"Error pushing to gsheets: {e}")

def pull_all_from_gsheets():
    """Pulls all tables from Google Sheets into local SQLite"""
    create_tables() # Ensure schema exists
    if not SPREADSHEET_ID:
        print("WARNING: SPREADSHEET_ID not found in secrets or environment. Skipping Google Sheets sync.")
        return
    try:
        print(f"Starting sync from Google Sheets (ID: {SPREADSHEET_ID[:5]}...)...")
        client = get_gsheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID)
        worksheets = sheet.worksheets()
        print(f"Found {len(worksheets)} worksheets in Google Sheets.")
        
        conn = get_connection()
        for ws in worksheets:
            table_name = ws.title
            if table_name in ['Maintenance_Data', 'melted_data']:
                continue
            
            print(f"Syncing table: {table_name}")
            data = ws.get_all_values()
            if data and len(data) > 0:
                headers = data[0]
                records = data[1:]
                df = pd.DataFrame(records, columns=headers)
                date_cols = ['last_maintenance_date', 'next_due_date', 'date', 'last_replacement_date']
                datetime_cols = ['taking_over_datetime', 'handing_over_datetime', 'breakdown_reported_datetime']
                
                for col in date_cols:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors='coerce', format='mixed').dt.strftime('%Y-%m-%d').fillna('')
                for col in datetime_cols:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors='coerce', format='mixed').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                        
                # Clear table first to perform a clean 'sync' while preserving schema
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"DELETE FROM {table_name}")
                    conn.commit()
                    df.to_sql(table_name, conn, if_exists='append', index=False)
                    print(f"Table {table_name} synced successfully with {len(records)} rows (preserved schema).")
                except Exception as e_sql:
                    # Fallback if table doesn't exist yet or columns mismatch
                    print(f"Schema mismatch or missing table for {table_name}, re-creating: {e_sql}")
                    df.to_sql(table_name, conn, if_exists='replace', index=False)
                    print(f"Table {table_name} recreated via pandas (schema may be lost).")
        conn.close()
        print("Google Sheets sync completed.")
        ensure_admin_exists() 
    except Exception as e:
        print(f"CRITICAL ERROR pulling from gsheets: {e}")
        # Ensure tables exist even if sync fails
        try:
            create_tables()
        except:
            pass

def determine_table_from_query(query):
    query = query.strip().upper()
    words = query.split()
    if not words: return None
    
    if words[0] == 'INSERT' and len(words) >= 3:
        if words[2] == 'OR': # INSERT OR IGNORE INTO table
            return words[5].replace('(', '')
        return words[2].replace('(', '')
    elif words[0] == 'UPDATE' and len(words) >= 2:
        return words[1]
    elif words[0] == 'DELETE' and len(words) >= 3:
        return words[2]
    return None

def execute_query(query, params=()):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    
    table_name = determine_table_from_query(query)
    if table_name:
        push_table_to_gsheets(table_name.lower())

def execute_many_query(query, params_list):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executemany(query, params_list)
    conn.commit()
    conn.close()
    
    table_name = determine_table_from_query(query)
    if table_name:
        push_table_to_gsheets(table_name.lower())

def get_dataframe(query, params=()):
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def save_dataframe(df, table_name, index=False):
    conn = get_connection()
    df.to_sql(table_name, conn, if_exists="replace", index=index)
    conn.close()
    push_table_to_gsheets(table_name)

def ensure_admin_exists():
    """Ensures that at least one admin user exists based on secrets if the table is empty or admin is missing."""
    if not INITIAL_ADMIN_PASSWORD:
        print("NOTE: INITIAL_ADMIN_PASSWORD not set in secrets. Skipping default admin check.")
        return
        
    try:
        conn = get_connection()
        cursor = conn.cursor()
        pwd_str = str(INITIAL_ADMIN_PASSWORD)
        
        cursor.execute("SELECT * FROM users WHERE username='admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('admin', pwd_str, 'Admin'))
            print("Default admin user created from secret.")
        else:
            # Sync password with secret if it changed or to ensure it works
            cursor.execute("UPDATE users SET password = ?, role = 'Admin' WHERE username = 'admin'", (pwd_str,))
            print("Admin user password synchronized with secret.")
        
        conn.commit()
        conn.close()
        
        # Pushing to gsheets ensures the Google Sheet master also has the updated secret-based password
        push_table_to_gsheets("users")
    except Exception as e:
        print(f"Warning: Could not ensure admin user: {e}")

def create_tables():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    """)
    
    # Cranes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cranes (
            id TEXT PRIMARY KEY,
            location TEXT,
            capacity TEXT,
            type TEXT,
            make TEXT,
            installation_year TEXT,
            status TEXT
        )
    """)
    
    # Maintenance Schedule table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crane_id TEXT,
            maintenance_type TEXT,
            last_maintenance_date TEXT,
            next_due_date TEXT,
            status TEXT,
            FOREIGN KEY (crane_id) REFERENCES cranes (id)
        )
    """)
    
    # Maintenance Logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            crane_id TEXT,
            maintenance_type TEXT,
            taking_over_datetime TEXT,
            handing_over_datetime TEXT,
            checklist_status TEXT,
            remarks TEXT,
            photo_path TEXT,
            FOREIGN KEY (crane_id) REFERENCES cranes (id)
        )
    """)
    
    # Breakdown Logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS breakdown_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crane_id TEXT,
            breakdown_reported_datetime TEXT,
            taking_over_datetime TEXT,
            handing_over_datetime TEXT,
            checklist_status TEXT,
            remarks TEXT,
            photo_path TEXT,
            failure_assembly TEXT,
            reported_failure_type TEXT,
            root_cause_failure TEXT,
            corrective_action TEXT,
            failure_component TEXT,
            failure_defect TEXT,
            FOREIGN KEY (crane_id) REFERENCES cranes (id)
        )
    """)
    
    # Spare Parts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spare_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_name TEXT,
            applicable_cranes TEXT,
            stock_quantity INTEGER,
            minimum_stock INTEGER,
            supplier TEXT,
            last_replacement_date TEXT,
            remarks TEXT
        )
    """)

    # Failure Assemblies
    cursor.execute("CREATE TABLE IF NOT EXISTS failure_assemblies (id INTEGER PRIMARY KEY AUTOINCREMENT, assembly_name TEXT UNIQUE)")
    # Failure Components
    cursor.execute("CREATE TABLE IF NOT EXISTS failure_components (id INTEGER PRIMARY KEY AUTOINCREMENT, assembly_name TEXT, component_name TEXT UNIQUE)")
    # Failure Defects
    cursor.execute("CREATE TABLE IF NOT EXISTS failure_defects (id INTEGER PRIMARY KEY AUTOINCREMENT, component_name TEXT, defect_name TEXT UNIQUE)")
    # Schedule Master
    cursor.execute("CREATE TABLE IF NOT EXISTS Schedule_Master (id INTEGER PRIMARY KEY AUTOINCREMENT, Schedule TEXT UNIQUE, Frequency INTEGER)")

    conn.commit()
    conn.close()
    print("Tables created/verified successfully.")
    ensure_admin_exists()
