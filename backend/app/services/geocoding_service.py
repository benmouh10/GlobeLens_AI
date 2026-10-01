"""
GlobeLens AI — Country Geocoding
Deterministic country -> coordinates lookup used to validate LLM output.

qwen2.5-coder:7b was geocoding four unrelated events to 38.8951,-77.0364
(downtown Washington DC) with location_country "United States" whenever it
could not place a story confidently. Those coordinates were never derived from
the reported country; they were the model's fallback for "I do not know".

Rather than trust the model, this validates coordinates against a bounding box
for the reported country and substitutes a centroid when they disagree.

Bounding boxes rather than centroids for validation: a centroid is a point, so
it cannot describe a country's extent. The US centroid sits in Kansas, ~21
degrees of longitude from Washington DC, which made a legitimately-placed DC
story look wrong. A bounding box accepts anywhere inside the country.
"""
from typing import NamedTuple, Optional


class CountryGeo(NamedTuple):
    centroid_lat: float
    centroid_lon: float
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


def _g(lat: float, lon: float, lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> CountryGeo:
    return CountryGeo(lat, lon, lat_min, lat_max, lon_min, lon_max)


# Overrides for large countries where the geometric centroid is a poor pin.
#
# The US centroid is 39.8,-98.6, which lands in Kansas: mathematically correct
# for the outline, useless as a map marker, because no story is "about" Kansas.
# These entries use the most populous metropolitan area instead, so US stories
# at least cluster in a region a reader recognises. This is still a single
# point and not a real geocode; only per-article city extraction could do
# better, and that needs a city->coordinate table.
_LARGE_COUNTRY_ANCHORS: dict[str, tuple[float, float]] = {
    "united states": (40.7, -74.0),   # New York metro
    "canada": (43.7, -79.4),          # Toronto
    "russia": (55.8, 37.6),           # Moscow
    "china": (39.9, 116.4),           # Beijing
    "brazil": (-23.6, -46.6),         # Sao Paulo
    "australia": (-33.9, 151.2),      # Sydney
    "india": (19.1, 72.9),            # Mumbai
    "argentina": (-34.6, -58.4),      # Buenos Aires
    "mexico": (19.4, -99.1),          # Mexico City
    "indonesia": (-6.2, 106.8),       # Jakarta
    "nigeria": (6.5, 3.4),            # Lagos
    "pakistan": (31.5, 74.3),         # Lahore
    "saudi arabia": (24.7, 46.7),     # Riyadh
    "turkey": (41.0, 29.0),           # Istanbul
    "iran": (35.7, 51.4),             # Tehran
    "france": (48.9, 2.4),            # Paris
    "germany": (52.5, 13.4),          # Berlin
    "spain": (40.4, -3.7),            # Madrid
    "italy": (41.9, 12.5),            # Rome
    "united kingdom": (51.5, -0.13),  # London
    "japan": (35.7, 139.7),           # Tokyo
}

# name: (centroid_lat, centroid_lon, lat_min, lat_max, lon_min, lon_max)
COUNTRY_GEO: dict[str, CountryGeo] = {
    "united states": _g(39.8, -98.6, 24.5, 49.4, -125.0, -66.9),
    "united kingdom": _g(54.0, -2.0, 49.9, 60.9, -8.6, 1.8),
    "france": _g(46.6, 2.4, 41.3, 51.1, -5.1, 9.6),
    "germany": _g(51.2, 10.4, 47.3, 55.1, 5.9, 15.0),
    "spain": _g(40.2, -3.7, 36.0, 43.8, -9.3, 3.3),
    "italy": _g(42.8, 12.6, 36.6, 47.1, 6.6, 18.5),
    "portugal": _g(39.6, -8.0, 36.9, 42.2, -9.5, -6.2),
    "netherlands": _g(52.2, 5.3, 50.7, 53.6, 3.3, 7.2),
    "belgium": _g(50.6, 4.6, 49.5, 51.5, 2.5, 6.4),
    "ireland": _g(53.3, -8.0, 51.4, 55.4, -10.6, -5.9),
    "sweden": _g(62.0, 15.0, 55.3, 69.1, 11.1, 24.2),
    "norway": _g(64.0, 12.0, 57.9, 71.2, 4.6, 31.1),
    "finland": _g(64.5, 26.0, 59.8, 70.1, 20.6, 31.6),
    "denmark": _g(56.1, 9.5, 54.6, 57.8, 8.1, 15.2),
    "poland": _g(52.0, 19.5, 49.0, 54.9, 14.1, 24.2),
    "greece": _g(39.0, 22.5, 34.9, 41.7, 19.4, 28.3),
    "austria": _g(47.6, 14.1, 46.4, 49.0, 9.5, 17.2),
    "switzerland": _g(46.9, 8.2, 45.8, 47.8, 5.9, 10.5),
    "czech republic": _g(49.8, 15.5, 48.6, 51.1, 12.1, 18.9),
    "hungary": _g(47.2, 19.3, 45.7, 48.6, 16.1, 22.9),
    "romania": _g(45.9, 25.0, 43.6, 48.3, 20.3, 29.7),
    "ukraine": _g(48.4, 31.2, 44.4, 52.4, 22.1, 40.2),
    "russia": _g(61.0, 90.0, 41.2, 81.9, 19.6, 180.0),
    "belarus": _g(53.0, 28.0, 51.3, 56.2, 23.2, 32.8),
    "turkey": _g(39.0, 35.2, 35.8, 42.1, 26.0, 44.8),
    "israel": _g(31.5, 34.9, 29.5, 33.3, 34.3, 35.9),
    "palestine": _g(31.9, 35.2, 31.2, 32.6, 34.2, 35.6),
    "gaza": _g(31.3, 34.4, 31.2, 31.6, 34.2, 34.6),
    "west bank": _g(31.9, 35.2, 31.3, 32.6, 34.2, 35.6),
    "lebanon": _g(33.9, 35.5, 33.1, 34.7, 35.1, 36.6),
    "syria": _g(34.8, 39.0, 32.3, 37.3, 35.7, 42.4),
    "iraq": _g(33.2, 43.7, 29.1, 37.4, 38.8, 48.6),
    "iran": _g(32.4, 53.7, 25.0, 39.8, 44.0, 63.3),
    "saudi arabia": _g(23.9, 45.1, 16.3, 32.2, 34.5, 55.7),
    "yemen": _g(15.4, 44.2, 12.1, 19.0, 42.5, 53.1),
    "egypt": _g(26.8, 30.8, 22.0, 31.7, 24.7, 36.9),
    "libya": _g(26.3, 17.2, 19.5, 33.2, 9.3, 25.2),
    "morocco": _g(31.8, -7.1, 27.7, 35.9, -13.2, -1.0),
    "algeria": _g(28.0, 1.7, 19.0, 37.1, -8.7, 12.0),
    "tunisia": _g(33.9, 9.5, 30.2, 37.5, 7.5, 11.6),
    "sudan": _g(12.9, 30.2, 8.7, 22.0, 21.8, 38.6),
    "south sudan": _g(7.9, 30.0, 3.5, 12.2, 24.1, 35.9),
    "ethiopia": _g(9.1, 40.5, 3.4, 14.9, 33.0, 48.0),
    "somalia": _g(5.2, 46.2, -1.7, 12.0, 40.9, 51.5),
    "kenya": _g(-0.02, 37.9, -4.7, 5.5, 33.9, 41.9),
    "uganda": _g(1.4, 32.3, -1.5, 4.2, 29.6, 35.0),
    "tanzania": _g(-6.4, 34.9, -11.7, -0.9, 29.3, 40.4),
    "rwanda": _g(-1.9, 29.9, -2.9, -1.1, 28.8, 30.9),
    "burundi": _g(-3.4, 29.9, -4.5, -2.3, 29.0, 30.9),
    "south africa": _g(-30.6, 22.9, -34.8, -22.1, 16.5, 32.9),
    "zimbabwe": _g(-19.0, 29.2, -22.4, -15.6, 25.2, 33.1),
    "zambia": _g(-13.1, 27.8, -18.1, -8.2, 22.0, 33.7),
    "nigeria": _g(9.1, 8.7, 4.3, 13.9, 2.7, 14.7),
    "ghana": _g(7.9, -1.0, 4.7, 11.2, -3.3, 1.3),
    "senegal": _g(14.5, -14.5, 12.3, 16.7, -17.6, -11.4),
    "mali": _g(17.6, -4.0, 10.2, 25.0, -12.2, 4.3),
    "dr congo": _g(-4.0, 21.8, -13.5, 5.4, 12.2, 31.3),
    "cameroon": _g(7.4, 12.4, 1.7, 13.1, 8.5, 16.2),
    "angola": _g(-11.2, 17.9, -18.0, -4.4, 11.7, 24.1),
    "mozambique": _g(-18.7, 35.5, -26.9, -10.5, 30.2, 40.8),
    "botswana": _g(-22.3, 24.7, -26.9, -17.8, 20.0, 29.4),
    "namibia": _g(-22.6, 17.1, -28.9, -17.0, 11.7, 25.3),
    "india": _g(20.6, 79.0, 6.7, 35.5, 68.2, 97.4),
    "pakistan": _g(30.4, 69.3, 23.7, 37.1, 60.9, 77.8),
    "bangladesh": _g(23.7, 90.4, 20.7, 26.6, 88.0, 92.7),
    "sri lanka": _g(7.9, 80.8, 5.9, 9.8, 79.7, 81.9),
    "nepal": _g(28.4, 84.1, 26.4, 30.4, 80.1, 88.2),
    "china": _g(35.9, 104.2, 18.2, 53.6, 73.5, 134.8),
    "japan": _g(36.2, 138.3, 24.0, 45.5, 122.9, 153.99),
    "south korea": _g(35.9, 127.8, 33.1, 38.6, 124.6, 131.0),
    "north korea": _g(40.3, 127.5, 37.7, 43.1, 124.3, 130.7),
    "taiwan": _g(23.7, 121.0, 21.9, 25.3, 120.0, 122.0),
    "hong kong": _g(22.3, 114.2, 22.1, 22.6, 113.8, 114.4),
    "vatican city": _g(41.9, 12.5, 41.9, 41.9, 12.4, 12.5),
    "saint kitts and nevis": _g(17.3, -62.7, 17.1, 17.4, -62.9, -62.5),
    "saint lucia": _g(13.9, -61.0, 13.7, 14.1, -61.1, -60.9),
    "saint vincent and the grenadines": _g(13.0, -61.2, 12.6, 13.4, -61.5, -61.0),
    "mongolia": _g(46.9, 103.8, 41.6, 52.1, 87.7, 119.9),
    "vietnam": _g(14.1, 108.3, 8.6, 23.4, 102.1, 109.5),
    "thailand": _g(15.9, 101.0, 5.6, 20.5, 97.3, 105.6),
    "philippines": _g(12.9, 121.8, 4.6, 21.1, 116.9, 126.6),
    "indonesia": _g(-0.8, 113.9, -11.0, 6.1, 95.0, 141.0),
    "malaysia": _g(4.2, 101.9, 0.9, 7.4, 99.6, 119.3),
    "singapore": _g(1.35, 103.8, 1.1, 1.5, 103.6, 104.0),
    "cambodia": _g(12.6, 105.0, 10.4, 14.7, 102.3, 107.6),
    "myanmar": _g(21.9, 96.0, 9.9, 28.5, 92.2, 101.2),
    "afghanistan": _g(33.9, 67.7, 29.4, 38.5, 60.5, 74.9),
    "kazakhstan": _g(48.0, 68.0, 40.6, 55.4, 46.5, 87.4),
    "uzbekistan": _g(41.4, 64.6, 37.2, 45.6, 56.0, 73.1),
    "kyrgyzstan": _g(41.2, 74.8, 39.2, 43.3, 69.3, 80.3),
    "azerbaijan": _g(40.1, 47.6, 38.4, 41.9, 44.8, 50.4),
    "georgia": _g(42.3, 43.4, 41.0, 43.6, 40.0, 46.7),
    "armenia": _g(40.1, 45.0, 38.8, 41.3, 43.4, 46.6),
    "canada": _g(56.1, -106.3, 41.7, 83.1, -141.0, -52.6),
    "mexico": _g(23.6, -102.6, 14.5, 32.7, -118.4, -86.7),
    "brazil": _g(-14.2, -51.9, -33.8, 5.3, -73.9, -34.8),
    "argentina": _g(-38.4, -63.6, -55.1, -21.8, -73.6, -53.6),
    "chile": _g(-35.7, -71.5, -55.9, -17.5, -75.6, -66.4),
    "colombia": _g(4.6, -74.3, -4.2, 12.4, -79.0, -66.9),
    "peru": _g(-9.2, -75.0, -18.4, -0.1, -81.4, -68.7),
    "venezuela": _g(6.4, -66.6, 0.6, 12.2, -73.4, -59.8),
    "bolivia": _g(-16.3, -63.6, -22.9, -9.7, -69.6, -57.5),
    "ecuador": _g(-1.8, -78.2, -5.0, 1.4, -81.0, -75.2),
    "australia": _g(-25.3, 133.8, -43.6, -10.7, 112.9, 153.6),
    "new zealand": _g(-40.9, 174.9, -47.3, -34.4, 166.5, 178.6),
    "papua new guinea": _g(-6.3, 143.9, -11.7, -1.4, 140.8, 155.9),
    "fiji": _g(-17.7, 178.1, -20.7, -16.1, 176.9, 179.9),
    "united arab emirates": _g(24.0, 54.0, 22.6, 26.1, 51.6, 56.4),
    "cote d ivoire": _g(7.5, -5.5, 4.3, 10.7, -8.6, -2.5),
    "north macedonia": _g(41.6, 21.7, 40.9, 42.4, 20.5, 23.0),
    "moldova": _g(47.4, 28.4, 45.5, 48.5, 26.6, 30.1),
    "kosovo": _g(42.6, 21.0, 41.1, 43.3, 20.0, 21.8),

    # --- remainder of the world ---
    # Europe
    "albania": _g(41.2, 20.2, 39.6, 42.7, 19.3, 21.1),
    "andorra": _g(42.5, 1.6, 42.4, 42.7, 1.4, 1.8),
    "iceland": _g(64.9, -19.0, 63.4, 66.6, -24.5, -13.5),
    "latvia": _g(56.9, 24.6, 55.7, 58.1, 21.0, 28.2),
    "lithuania": _g(55.2, 23.9, 53.9, 56.4, 20.9, 26.9),
    "luxembourg": _g(49.8, 6.1, 49.4, 50.2, 5.7, 6.6),
    "malta": _g(35.9, 14.4, 35.8, 36.1, 14.2, 14.6),
    "monaco": _g(43.7, 7.4, 43.7, 43.8, 7.4, 7.5),
    "san marino": _g(43.9, 12.5, 43.9, 44.0, 12.4, 12.6),
    "slovenia": _g(46.2, 15.0, 45.4, 46.9, 13.4, 16.6),
    "slovakia": _g(48.7, 19.7, 47.7, 49.6, 16.8, 22.6),
    "serbia": _g(44.0, 21.0, 42.2, 46.6, 18.8, 23.0),
    "montenegro": _g(42.7, 19.4, 41.8, 43.6, 18.4, 20.4),
    "bosnia and herzegovina": _g(44.0, 17.7, 42.6, 45.3, 15.7, 19.6),
    "cyprus": _g(35.1, 33.4, 34.6, 35.7, 32.3, 34.6),

    # Middle East and Gulf
    "jordan": _g(31.2, 36.5, 29.2, 33.4, 34.9, 39.3),
    "qatar": _g(25.4, 51.2, 24.5, 26.2, 50.8, 51.6),
    "kuwait": _g(29.3, 47.5, 28.5, 30.1, 46.6, 48.4),
    "bahrain": _g(26.0, 50.6, 25.7, 26.3, 50.4, 50.8),
    "oman": _g(21.5, 55.9, 16.6, 26.4, 52.0, 59.8),

    # Central, South and Southeast Asia
    "nepal": _g(28.4, 84.1, 26.4, 30.4, 80.1, 88.2),
    "bhutan": _g(27.5, 90.5, 26.7, 28.3, 88.7, 92.1),
    "maldives": _g(3.2, 73.2, -0.7, 7.1, 72.6, 73.7),
    "brunei": _g(4.5, 114.7, 4.3, 4.7, 114.1, 115.3),
    "laos": _g(19.9, 102.5, 13.9, 22.5, 100.1, 107.7),
    "tajikistan": _g(38.9, 71.3, 37.2, 40.6, 67.3, 75.2),
    "turkmenistan": _g(39.1, 59.5, 35.1, 42.8, 52.4, 66.7),
    "timor-leste": _g(-8.9, 125.7, -9.5, -8.1, 124.0, 127.3),

    # Africa
    "algeria": _g(28.0, 1.7, 19.0, 37.1, -8.7, 12.0),
    "benin": _g(9.3, 2.3, 6.2, 12.4, 0.8, 3.9),
    "burkina faso": _g(12.2, -1.6, 9.4, 15.1, -5.5, 2.4),
    "cabo verde": _g(16.0, -24.0, 14.8, 17.1, -25.4, -22.7),
    "cape verde": _g(16.0, -24.0, 14.8, 17.1, -25.4, -22.7),
    "central african republic": _g(6.6, 20.9, 2.2, 11.0, 14.4, 27.5),
    "chad": _g(15.5, 18.7, 7.4, 23.4, 13.5, 24.0),
    "comoros": _g(-11.9, 43.9, -12.4, -11.3, 43.2, 44.5),
    "republic of the congo": _g(-0.7, 15.8, -5.1, 3.7, 11.1, 19.0),
    "congo republic": _g(-0.7, 15.8, -5.1, 3.7, 11.1, 19.0),
    "congo-brazzaville": _g(-0.7, 15.8, -5.1, 3.7, 11.1, 19.0),
    "djibouti": _g(11.8, 42.6, 10.9, 12.7, 41.7, 43.4),
    "equatorial guinea": _g(1.7, 10.3, -1.5, 3.8, 8.4, 11.3),
    "eritrea": _g(15.2, 39.8, 12.3, 18.1, 36.9, 43.1),
    "eswatini": _g(-26.5, 31.5, -27.3, -25.7, 30.8, 32.1),
    "swaziland": _g(-26.5, 31.5, -27.3, -25.7, 30.8, 32.1),
    "gabon": _g(-0.2, 11.8, -3.9, 2.3, 8.7, 14.5),
    "gambia": _g(13.4, -15.3, 13.1, 13.8, -16.8, -13.8),
    "guinea": _g(10.4, -11.0, 7.2, 12.7, -15.1, -7.6),
    "guinea-bissau": _g(11.8, -15.2, 11.0, 12.7, -16.7, -13.6),
    "lesotho": _g(-29.6, 28.2, -30.7, -28.6, 27.0, 29.5),
    "liberia": _g(6.4, -9.4, 4.4, 8.6, -11.5, -7.4),
    "madagascar": _g(-18.8, 46.3, -25.6, -11.9, 43.2, 50.5),
    "malawi": _g(-13.3, 34.3, -17.1, -9.4, 32.7, 35.9),
    "mauritania": _g(21.0, -10.9, 14.7, 27.3, -17.1, -4.8),
    "mauritius": _g(-20.3, 57.5, -20.5, -20.1, 57.3, 57.8),
    "niger": _g(17.6, 8.1, 11.7, 23.5, 0.2, 16.0),
    "sao tome and principe": _g(0.2, 6.6, -0.1, 0.5, 6.4, 6.8),
    "seychelles": _g(-4.7, 55.5, -10.4, -4.3, 54.8, 56.1),
    "sierra leone": _g(8.5, -11.8, 6.9, 10.0, -13.4, -10.3),
    "togo": _g(8.6, 1.1, 6.1, 11.1, -1.1, 3.3),

    # Americas
    "antigua and barbuda": _g(17.1, -61.8, 16.7, 17.7, -61.9, -61.6),
    "bahamas": _g(24.3, -76.0, 20.9, 27.3, -79.8, -72.7),
    "barbados": _g(13.2, -59.5, 13.0, 13.3, -59.7, -59.4),
    "belize": _g(17.2, -88.9, 15.9, 18.5, -89.2, -87.8),
    "costa rica": _g(9.7, -84.0, 8.0, 11.2, -85.9, -82.6),
    "cuba": _g(21.5, -79.0, 19.8, 23.2, -84.9, -74.1),
    "dominica": _g(15.4, -61.4, 15.2, 15.6, -61.5, -61.2),
    "dominican republic": _g(18.7, -70.2, 17.6, 19.9, -71.9, -68.3),
    "el salvador": _g(13.8, -88.9, 13.1, 14.4, -90.1, -87.7),
    "grenada": _g(12.1, -61.7, 12.0, 12.3, -61.8, -61.6),
    "guatemala": _g(15.6, -90.3, 13.7, 17.8, -92.2, -88.2),
    "guyana": _g(5.0, -58.9, 1.2, 8.6, -61.4, -56.5),
    "haiti": _g(19.0, -72.3, 18.0, 20.1, -74.5, -68.4),
    "honduras": _g(15.2, -86.2, 13.0, 16.5, -89.4, -83.1),
    "jamaica": _g(18.1, -77.3, 17.7, 18.5, -78.4, -76.2),
    "nicaragua": _g(12.9, -85.2, 10.7, 15.0, -87.7, -83.1),
    "panama": _g(8.5, -80.8, 7.2, 9.6, -83.0, -77.2),
    "suriname": _g(4.1, -56.0, 2.0, 6.0, -58.1, -53.9),
    "trinidad and tobago": _g(10.7, -61.2, 10.0, 11.4, -61.9, -60.5),
    "uruguay": _g(-32.5, -55.8, -35.0, -30.1, -58.5, -53.1),

    # Oceania and the Pacific
    "fiji": _g(-17.7, 178.1, -20.7, -16.1, 176.9, 179.9),
    "kiribati": _g(1.4, 173.0, -11.5, 4.7, 169.5, 180.0),
    "marshall islands": _g(7.1, 171.2, 4.6, 14.6, 162.0, 173.0),
    "micronesia": _g(6.9, 158.2, 1.0, 10.1, 137.4, 163.1),
    "nauru": _g(-0.5, 166.9, -0.6, -0.4, 166.9, 167.0),
    "palau": _g(7.5, 134.6, 7.0, 8.1, 134.1, 134.7),
    "samoa": _g(-13.8, -172.1, -14.1, -13.4, -172.9, -171.4),
    "solomon islands": _g(-9.6, 160.2, -12.0, -6.6, 155.7, 167.0),
    "tonga": _g(-21.2, -175.2, -23.9, -18.5, -175.4, -173.9),
    "tuvalu": _g(-8.5, 179.1, -9.4, -7.4, 176.0, 180.0),
    "vanuatu": _g(-16.3, 167.5, -20.3, -13.1, 166.5, 170.2),
}

_ALIASES = {
    "usa": "united states",
    "u.s.": "united states",
    "u.s.a.": "united states",
    "us": "united states",
    "america": "united states",
    "united states of america": "united states",
    "britain": "united kingdom",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "wales": "united kingdom",
    "northern ireland": "united kingdom",
    "uk": "united kingdom",
    "uae": "united arab emirates",
    "u.a.e.": "united arab emirates",
    "emirates": "united arab emirates",
    "drc": "dr congo",
    "democratic republic of the congo": "dr congo",
    "congo": "dr congo",
    "czechia": "czech republic",
    "south korea": "south korea",
    "republic of korea": "south korea",
    "korea": "south korea",
    "dprk": "north korea",
    "hong kong sar": "hong kong",
    "ua": "ukraine",
    "ivory coast": "cote d ivoire",
    "cote divoire": "cote d ivoire",
    "burma": "myanmar",
    "macedonia": "north macedonia",
    "bosnia": "bosnia and herzegovina",
    "bosnia & herzegovina": "bosnia and herzegovina",
    "bosnia-herzegovina": "bosnia and herzegovina",
    "t&t": "trinidad and tobago",
    "trinidad": "trinidad and tobago",
    "drc": "dr congo",
    "democratic republic of congo": "dr congo",
    "democratic republic of the congo": "dr congo",
    "dem. rep. of the congo": "dr congo",
    "zaire": "dr congo",
    "congo": "republic of the congo",
    "republic of congo": "republic of the congo",
    "south korean republic": "south korea",
    "korea, south": "south korea",
    "korea, north": "north korea",
    "uae": "united arab emirates",
    "u.a.e.": "united arab emirates",
    "emirates": "united arab emirates",
    "holland": "netherlands",
    "the netherlands": "netherlands",
    "turkiye": "turkey",
    "north macedonia ": "north macedonia",
    "republic of korea": "south korea",
    "republic of ireland": "ireland",
    "czechia": "czech republic",
    "cote d'ivoire": "cote d ivoire",
    "côte d'ivoire": "cote d ivoire",
    "ivory coast": "cote d ivoire",
    "lao pdr": "laos",
    "lao people's democratic republic": "laos",
    "east timor": "timor-leste",
    "eswatini ": "eswatini",
    "swaziland": "eswatini",
    "vatican": "vatican city",
    "holy see": "vatican city",
    "myanmar ": "myanmar",
    "russian federation": "russia",
    "russian": "russia",
    "iran, islamic republic of": "iran",
    "islamic republic of iran": "iran",
    "viet nam": "vietnam",
    "türkiye": "turkey",
    "the bahamas": "bahamas",
    "republic of seychelles": "seychelles",
    "antigua": "antigua and barbuda",
    "st kitts and nevis": "saint kitts and nevis",
    "saint kitts and nevis": "saint kitts and nevis",
    "st lucia": "saint lucia",
    "saint lucia": "saint lucia",
    "st vincent and the grenadines": "saint vincent and the grenadines",
    "saint vincent and the grenadines": "saint vincent and the grenadines",
    "micronesia, federated states of": "micronesia",
    "federated states of micronesia": "micronesia",
    "democratic republic of the congos": "dr congo",
}


def normalize_country(name: Optional[str]) -> Optional[str]:
    """Map an LLM-supplied country string onto a known country, if possible."""
    if not name:
        return None

    cleaned = name.strip().lower().strip(".,")
    cleaned = cleaned.replace("the ", "")

    if cleaned in COUNTRY_GEO:
        return cleaned

    if cleaned in _ALIASES:
        return _ALIASES[cleaned]

    # "U.S." loses its final dot to strip(".,") above, so try a dot-free form.
    undotted = cleaned.replace(".", "")
    if undotted in _ALIASES:
        return _ALIASES[undotted]

    return None


def display_name(country: Optional[str]) -> Optional[str]:
    """Canonical table key -> human-readable name, e.g. "united states" -> "United States".

    The geocoder keys are lowercase because they are matched case-insensitively,
    but they are stored and shown to users, so they must not stay lowercase.
    """
    normalized = normalize_country(country)
    if not normalized:
        return None

    # Prefer an explicit display spelling so we do not have to title-case
    # (which produces "Bosnia And Herzegovina" and "Vatican City").
    pretty = _DISPLAY_NAMES.get(normalized)
    if pretty:
        return pretty

    words = [_LOWER_WORDS.get(w, w.capitalize()) for w in normalized.split()]
    return " ".join(words)


# Words that stay lowercase inside a country name.
_LOWER_WORDS = {
    "and": "and",
    "of": "of",
    "the": "the",
    "de": "de",
}

# Canonical display spellings for names .title() gets wrong.
_DISPLAY_NAMES = {
    "dr congo": "DR Congo",
    "vatican city": "Vatican City",
    "republic of the congo": "Republic of the Congo",
    "united states": "United States",
    "united kingdom": "United Kingdom",
    "united arab emirates": "United Arab Emirates",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "south africa": "South Africa",
    "south sudan": "South Sudan",
    "sri lanka": "Sri Lanka",
    "saudi arabia": "Saudi Arabia",
    "trinidad and tobago": "Trinidad and Tobago",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "dominican republic": "Dominican Republic",
    "czech republic": "Czech Republic",
    "papua new guinea": "Papua New Guinea",
    "costa rica": "Costa Rica",
    "el salvador": "El Salvador",
    "timor-leste": "Timor-Leste",
    "cote d ivoire": "Cote d'Ivoire",
    "sao tome and principe": "Sao Tome and Principe",
    "saint kitts and nevis": "Saint Kitts and Nevis",
    "saint lucia": "Saint Lucia",
    "saint vincent and the grenadines": "Saint Vincent and the Grenadines",
    "antigua and barbuda": "Antigua and Barbuda",
    "new zealand": "New Zealand",
    "hong kong": "Hong Kong",
    "sierra leone": "Sierra Leone",
    "guinea-bissau": "Guinea-Bissau",
    "tanzania": "Tanzania",
    "eswatini": "Eswatini",
    "north macedonia": "North Macedonia",
    "equatorial guinea": "Equatorial Guinea",
    "central african republic": "Central African Republic",
    "republic of the congo": "Republic of the Congo",
    "congo republic": "Republic of the Congo",
    "congo-brazzaville": "Republic of the Congo",
    "cape verde": "Cabo Verde",
    "turkmenistan": "Turkmenistan",
    "tajikistan": "Tajikistan",
    "mauritania": "Mauritania",
    "micronesia": "Micronesia",
    "marshall islands": "Marshall Islands",
    "solomon islands": "Solomon Islands",
    "seychelles": "Seychelles",
    "comoros": "Comoros",
}


def geo_for(country: Optional[str]) -> Optional[CountryGeo]:
    """Resolve a country name to its geometry, or None when unrecognised."""
    normalized = normalize_country(country)
    if not normalized:
        return None
    geo = COUNTRY_GEO[normalized]
    anchor = _LARGE_COUNTRY_ANCHORS.get(normalized)
    if anchor is not None:
        # Keep the bounding box for validation, swap only the marker point.
        geo = geo._replace(centroid_lat=anchor[0], centroid_lon=anchor[1])
    return geo


def centroid_for(country: Optional[str]) -> Optional[tuple[float, float]]:
    """Approximate centre point for a country, used when coords are unusable."""
    geo = geo_for(country)
    if geo is None:
        return None
    return geo.centroid_lat, geo.centroid_lon


def coordinates_are_consistent(
    country: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    slack_degrees: float = 2.0,
) -> Optional[str]:
    """
    Validate LLM-supplied coordinates against the reported country.

    Returns None when acceptable, otherwise a reason string. A small slack
    band is allowed outside the bounding box so that events on coastlines,
    disputed borders and slightly-wrong city picks still pass; the point is to
    catch the "model defaulted to Washington DC" failure, not to enforce
    precision.
    """
    geo = geo_for(country)
    if geo is None:
        return f"unrecognised country {country!r}"

    if latitude is None or longitude is None:
        return "missing coordinates"

    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return f"coordinates out of range ({latitude}, {longitude})"

    within = (
        geo.lat_min - slack_degrees <= latitude <= geo.lat_max + slack_degrees
        and geo.lon_min - slack_degrees <= longitude <= geo.lon_max + slack_degrees
    )
    if not within:
        return (
            f"coordinates {latitude:.2f},{longitude:.2f} fall outside "
            f"{country!r} bounds "
            f"lat[{geo.lat_min:.1f},{geo.lat_max:.1f}] "
            f"lon[{geo.lon_min:.1f},{geo.lon_max:.1f}]"
        )

    return None


def resolve_coordinates(
    country: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Return trustworthy (lat, lon) for an event.

    Keeps the model's coordinates when they fall inside the reported country.
    Otherwise substitutes the country centroid. Returns None coordinates when
    the country is unknown, so the map omits the marker instead of plotting a
    fabricated position.
    """
    problem = coordinates_are_consistent(country, latitude, longitude)
    if problem is None:
        return latitude, longitude, None

    centroid = centroid_for(country)
    if centroid is not None:
        return centroid[0], centroid[1], f"replaced coordinates ({problem})"

    return None, None, f"dropped coordinates ({problem})"