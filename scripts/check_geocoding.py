from app.services.geocoding_service import coordinates_are_consistent, resolve_coordinates

CASES = [
    ("United States", 38.8951, -77.0364, "the DC fallback"),
    ("Ethiopia", 38.8951, -77.0364, "Ethiopian army mislocated"),
    ("France", 48.8566, 2.3522, "Paris for France"),
    ("Saudi Arabia", 21.5236, 39.1212, "Tabuk for Saudi"),
    ("United States", 38.9072, -77.0369, "Washington DC, honest"),
    ("Palestine", 31.9522, 34.8515, "Gaza City"),
    ("Ukraine", 50.45, 30.5236, "Kyiv"),
    ("Atlantis", 10.0, 10.0, "unknown country"),
    ("Japan", None, None, "missing coords"),
    ("USA", 39.8, -98.6, "alias + centroid"),
]

for country, lat, lon, label in CASES:
    fixed_lat, fixed_lon, note = resolve_coordinates(country, lat, lon)
    verdict = "OK" if note is None else "FIXED"
    print(
        f"  {label:22s} {country:14s} {str(lat):8s}{str(lon):9s} "
        f"-> {verdict:5s} {fixed_lat},{fixed_lon}"
        + (f"   ({note[:58]})" if note else "")
    )