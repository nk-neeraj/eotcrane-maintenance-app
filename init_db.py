import pandas as pd
import sqlite3
import os
from datetime import timedelta
import database as db

EXCEL_FILE = "Schedule  date of EOT Crane.xlsx"

def init_database():
    print("Creating DB tables...")
    db.create_tables()
    
    print("Loading Excel data...")
    try:
        xl = pd.ExcelFile(EXCEL_FILE)
        eot_master = xl.parse("EOT_Master")
        melted_data = xl.parse("melted_data")
        schedule_master = xl.parse("Schedule_Master")
        schedule_freq = dict(zip(schedule_master['Schedule'], schedule_master['Frequency']))
        
        conn = db.get_connection()
        
        print("Populating Cranes Master...")
        for _, row in eot_master.iterrows():
            crane_id = str(row['MW_No'])
            location = str(row['Location'])
            capacity = str(row['Capacity'])
            crane_type = str(row['Type'])
            
            # Insert into DB if not exists
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM cranes WHERE id=?", (crane_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO cranes (id, location, capacity, type, make, installation_year, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (crane_id, location, capacity, crane_type, 'Unknown', 'Unknown', 'Active'))
        
        print("Populating Maintenance Schedule...")
        for _, row in melted_data.iterrows():
            crane_id = str(row['MW_No'])
            sch_type = str(row['Schedule']) # e.g. S1A
            maintenance_date = pd.to_datetime(row['Maintenance_Date'], errors='coerce')
            
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
        print("Database initialized successfully!")
        
    except Exception as e:
        print(f"Error initializing database: {e}")

if __name__ == "__main__":
    init_database()
