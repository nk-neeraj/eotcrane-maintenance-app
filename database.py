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
    SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
    WEBHOOK_URL = st.secrets["WEBHOOK_URL"]
except Exception:
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

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
    try:
        client = get_gsheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID)
        worksheets = sheet.worksheets()
        
        conn = get_connection()
        for ws in worksheets:
            table_name = ws.title
            if table_name in ['Maintenance_Data', 'melted_data']:
                continue
            
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
                        
                df.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.close()
    except Exception as e:
        print(f"Error pulling from gsheets: {e}")

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

def create_tables():
    pass
