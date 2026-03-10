import sqlite3
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import time

DB_NAME = "cmms.db"
SPREADSHEET_ID = '19pE1liozVcvspe3WHXQLoKsZMTf-2L4o6aUm80pwx9A'
JSON_KEY = 'plantmaintence-d2bfc889466e.json'

scopes = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
creds = Credentials.from_service_account_file(JSON_KEY, scopes=scopes)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)

conn = sqlite3.connect(DB_NAME)

tables = [
    "cranes", 
    "maintenance_schedule", 
    "maintenance_logs", 
    "spare_parts", 
    "breakdown_logs", 
    "failure_assemblies", 
    "failure_components", 
    "failure_defects", 
    "users"
]

for table in tables:
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    # Check if sheet exists
    try:
        ws = sheet.worksheet(table)
        print(f"Sheet {table} exists, clearing...")
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        print(f"Creating sheet {table}...")
        ws = sheet.add_worksheet(title=table, rows=str(max(100, len(df) + 10)), cols=str(max(20, len(df.columns) + 5)))
    
    # Write dataframe to sheet
    if not df.empty:
        # Fill NaN with empty string
        df = df.fillna('')
        # convert dates/times to string properly if needed
        data = [df.columns.values.tolist()] + df.values.tolist()
        ws.update(range_name='A1', values=data)
    else:
        ws.update(range_name='A1', values=[df.columns.values.tolist()])
    
    print(f"Migrated {table} ({len(df)} rows)")
    time.sleep(2) # Avoid rate limits

conn.close()
print("Migration completed successfully!")
