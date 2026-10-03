import io

from PIL import Image, ImageDraw


def make_image(color=(20, 20, 20), accent=(200, 30, 30), size=(240, 240), fmt="JPEG") -> bytes:
    """Synthetic 'backpack' photo: a dark rounded shape with a coloured keychain dot."""
    img = Image.new("RGB", size, (235, 235, 235))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((50, 40, 190, 210), radius=30, fill=color)
    d.ellipse((160, 60, 185, 85), fill=accent)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


LOST_BACKPACK = {
    "report_type": "LOST",
    "category": "Backpack",
    "name": "Black backpack",
    "description": "Black JanSport backpack with a laptop compartment, lost near the main library around 3 PM.",
    "color": "Black",
    "brand": "JanSport",
    "distinctive_features": "Name tag with initials inside the front pocket",
    "private_details": "Inside: blue calculus notebook, Casio calculator and a green water bottle",
    "date_time": "2026-10-01T15:00:00Z",
    "location": "Outside the Lecture Theatre",
    "place_key": "lecture-theatre",
}

FOUND_BACKPACK = {
    "report_type": "FOUND",
    "category": "Bag",
    "name": "Black backpack",
    "description": "Found a black JanSport backpack on a bench outside the library.",
    "color": "black",
    "brand": "Jansport",
    "distinctive_features": "Has a name tag with initials inside the front pocket",
    "private_details": "Contains a blue notebook with calculus notes and a calculator",
    "date_time": "2026-10-01T15:30:00Z",
    "location": "Bench near Allah Wala Chowk",
    "location_type": "gps",
    "latitude": 31.578850,  # ~60 m from the Lecture Theatre
    "longitude": 74.356760,
}

FOUND_UNRELATED = {
    "report_type": "FOUND",
    "category": "Phone",
    "name": "Silver Samsung phone",
    "description": "Silver Samsung phone found in the cafeteria.",
    "color": "silver",
    "brand": "Samsung",
    "date_time": "2026-10-01T16:00:00Z",
    "place_key": "sports-grounds",
}

# Reference points for geofence tests (WGS84)
CAMPUS_POINT = (31.579303, 74.357127)  # Department of Civil Engineering (OSM)
NEARBY_POINT = (31.5745, 74.3560)  # G.T. Road, ~250 m south of the campus boundary
OUTSIDE_POINT = (31.5925, 74.3095)  # Minar-e-Pakistan, ~4 km away
