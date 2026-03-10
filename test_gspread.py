import gspread
from google.oauth2.service_account import Credentials

scopes = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
creds = Credentials.from_service_account_file('plantmaintence-d2bfc889466e.json', scopes=scopes)
client = gspread.authorize(creds)

try:
    sheet = client.open_by_key('19pE1liozVcvspe3WHXQLoKsZMTf-2L4o6aUm80pwx9A')
    print("Worksheets:")
    for ws in sheet.worksheets():
        print(f"- {ws.title}")
except Exception as e:
    print(f"Error: {e}")
