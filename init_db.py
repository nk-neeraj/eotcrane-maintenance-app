import pandas as pd
import sqlite3
import os
from datetime import timedelta
import db as db

EXCEL_FILE = "Schedule  date of EOT Crane.xlsx"

def init_database():
    print("Creating DB tables...")
    db.create_tables()
    
    print("Loading data from Google Sheets instead of local Excel...")
    try:
        client = db.get_gsheets_client()
        sheet = client.open_by_key(db.SPREADSHEET_ID)
        
        # Helper to fetch worksheet to pandas
        def get_ws_df(title):
            ws = sheet.worksheet(title)
            data = ws.get_all_values()
            return pd.DataFrame(data[1:], columns=data[0]) if data else pd.DataFrame()

        eot_master = get_ws_df("EOT_Master")
        melted_data = get_ws_df("melted_data")
        schedule_master = get_ws_df("Schedule_Master")
        schedule_freq = dict(zip(schedule_master['Schedule'], pd.to_numeric(schedule_master['Frequency'], errors='coerce').fillna(30)))
        
        conn = db.get_connection()
        
        print("Populating Cranes Master from gsheets...")
        for _, row in eot_master.iterrows():
            crane_id = str(row.get('MW_No', ''))
            if not crane_id: continue
            location = str(row.get('Location', ''))
            capacity = str(row.get('Capacity', ''))
            crane_type = str(row.get('Type', ''))
            
            # Insert into DB if not exists
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM cranes WHERE id=?", (crane_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO cranes (id, location, capacity, type, make, installation_year, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (crane_id, location, capacity, crane_type, 'Unknown', 'Unknown', 'Active'))
        
        print("Populating Maintenance Schedule from gsheets...")
        for _, row in melted_data.iterrows():
            crane_id = str(row.get('MW_No', ''))
            if not crane_id: continue
            sch_type = str(row.get('Schedule', '')) # e.g. S1A
            maintenance_date = pd.to_datetime(row.get('Maintenance_Date'), errors='coerce')
            
            if pd.isna(maintenance_date):
                continue
                
            # Get specific frequency based on the exact Schedule Master entry (default 30 if missing)
            days_add = schedule_freq.get(sch_type, 30)
            mtype = sch_type
                
            next_due = maintenance_date + pd.Timedelta(days=days_add)
            
            cursor.execute("SELECT id FROM maintenance_schedule WHERE crane_id=? AND maintenance_type=?", (crane_id, mtype))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO maintenance_schedule (crane_id, maintenance_type, last_maintenance_date, next_due_date, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (crane_id, mtype, maintenance_date.strftime('%Y-%m-%d'), next_due.strftime('%Y-%m-%d'), 'OK'))
        
        conn.commit()
        conn.close()
        
        print("Fetching remaining tables from gsheets...")
        db.pull_all_from_gsheets()
        
        print("Database initialized successfully!")
        
    except Exception as e:
        print(f"Error initializing database: {e}")

if __name__ == "__main__":
    init_database()
