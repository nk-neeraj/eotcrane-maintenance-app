import pandas as pd

file_path = "g:/My Drive/BLW/Plant-II/EOT Crane Safety drive/crane_maint/Schedule  date of EOT Crane.xlsx"

try:
    xl = pd.ExcelFile(file_path)
    print("Sheet names:", xl.sheet_names)
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        print(f"\n--- Sheet: {sheet} ---")
        print("Columns:", df.columns.tolist())
        print("First row:", df.iloc[0].to_dict() if not df.empty else "Empty")
except Exception as e:
    print("Error:", e)
