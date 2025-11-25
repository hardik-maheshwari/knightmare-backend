import uuid


def generate_game_id(length: int = 10) -> str:
    """
    Generates a unique, URL-safe, and random-based identifier for a game.
    """
    # uuid.uuid4() generates a random 128-bit UUID object.
    # .bytes converts it to a 16-byte sequence.
    # .b64encode() encodes these bytes into a URL-safe Base64 representation.
    # .decode('utf-8') converts the result back to a string.
    # The [:-2] removes the '==' padding from the end of the Base64 string.
    # The [:length] slices the string to the desired length.

    # A more modern and direct approach is to use urlsafe_b64encode
    from base64 import urlsafe_b64encode

    # Generate a random 16-byte UUID
    random_uuid = uuid.uuid4()

    # Encode the bytes using URL-safe Base64, decode to a string, and strip padding
    encoded_uuid = urlsafe_b64encode(random_uuid.bytes).decode("utf-8").rstrip("=")

    # Slice to the desired length
    return encoded_uuid[:length]
