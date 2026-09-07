from mtaa import tanzania

# Populate the district dropdown
districts = list(tanzania.get("Dar-es-salaam").districts)

# After the user selects Kinondoni, populate the ward dropdown
wards = list(
    tanzania.get("Dar-es-salaam").districts.get("Kinondoni").wards
)
print(wards)