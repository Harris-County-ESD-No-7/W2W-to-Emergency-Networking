# =========================
# Lookup tables
# =========================

# Person lookup (W2W → EN)
# Use Postman to pull a list from each system. 
# I used 9999999 for Not Assigned.
W2W_TO_EN: Dict[str, str] = {
    "317595647": "9999999", # CADET
    "318972808": "67151", # Joe Robert
    "145773476": "67153", # Sergio Torres
    "318965955": "67152", # Tommy Espinoza
    "181281996": "9999999", # 70 STATION
    "181282000": "9999999", # 71 STATION
    "181282005": "9999999", # 72 STATION
    "181282008": "9999999", # 73 STATION
    "181282010": "9999999", # 74 STATION
    "181282012": "9999999", # 75 STATION
    "181282015": "9999999", # 76 STATION
    "181282017": "9999999", # 77 STATION
    "181282019": "9999999", # 78 STATION
}

# Position → Equipment call sign
POSITION_TO_EQUIPMENT: Dict[str, str] = {
    "127517298": "{Matching unit in EN}", ### Match the unit in EN in plain text. This will likely be E72 or similar.
    "127517542": "{Matching unit in EN}",
}
