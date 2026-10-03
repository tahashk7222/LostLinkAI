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
    "distinctive_features": "Red keychain on the front zipper",
    "private_details": "Inside: blue calculus notebook, Casio calculator and a green water bottle",
    "date_time": "2026-10-01T15:00:00Z",
    "location": "Main Library entrance",
    "latitude": 33.6425,
    "longitude": 72.9930,
}

FOUND_BACKPACK = {
    "report_type": "FOUND",
    "category": "Bag",
    "name": "Black backpack",
    "description": "Found a black JanSport backpack on a bench outside the library.",
    "color": "black",
    "brand": "Jansport",
    "distinctive_features": "Has a red keychain attached to the zipper",
    "private_details": "Contains a blue notebook with calculus notes and a calculator",
    "date_time": "2026-10-01T15:30:00Z",
    "location": "Library courtyard bench",
    "latitude": 33.6431,
    "longitude": 72.9941,
}

FOUND_UNRELATED = {
    "report_type": "FOUND",
    "category": "Phone",
    "name": "Silver Samsung phone",
    "description": "Silver Samsung phone found in the cafeteria.",
    "color": "silver",
    "brand": "Samsung",
    "date_time": "2026-10-01T16:00:00Z",
    "location": "Cafeteria",
    "latitude": 33.6500,
    "longitude": 73.0100,
}
