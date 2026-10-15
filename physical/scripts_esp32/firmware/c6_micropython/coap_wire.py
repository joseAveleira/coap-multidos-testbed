"""Small CoAP codec shared by the C6 client and host validation tests."""


def request(mid, token, path="sensor", block=None, confirmable=False):
    if len(token) != 4 or path not in ("sensor", "large"):
        raise ValueError("Invalid token/resource")
    packet = bytes((0x44 if confirmable else 0x54, 1, mid >> 8, mid & 255)) + token
    packet += bytes((0xB0 | len(path),)) + path.encode()
    if block is not None:
        if path != "large" or not 0 <= block < 32:
            raise ValueError("Invalid block")
        value = (block << 4) | 6
        encoded = bytes((value,)) if value < 256 else bytes((value >> 8, value & 255))
        packet += bytes((0xC0 | len(encoded),)) + encoded
    return packet


def decode(packet):
    if len(packet) < 4 or packet[0] >> 6 != 1 or packet[0] & 15 > 8:
        raise ValueError("Invalid CoAP header")
    token_length = packet[0] & 15
    at = 4 + token_length
    if at > len(packet):
        raise ValueError("Truncated token")
    result = {"type": (packet[0] >> 4) & 3, "code": packet[1],
              "mid": packet[2] * 256 + packet[3], "token": packet[4:at],
              "etag": None, "block": None, "payload": b""}
    option = 0
    while at < len(packet):
        byte = packet[at]; at += 1
        if byte == 255:
            if at == len(packet):
                raise ValueError("Empty payload marker")
            result["payload"] = packet[at:]
            break
        values = []
        for nibble in (byte >> 4, byte & 15):
            if nibble == 15:
                raise ValueError("Reserved option encoding")
            count = 1 if nibble == 13 else 2 if nibble == 14 else 0
            if at + count > len(packet):
                raise ValueError("Truncated option extension")
            value = nibble if not count else 13 + packet[at] if count == 1 else 269 + packet[at] * 256 + packet[at + 1]
            at += count; values.append(value)
        delta, length = values
        option += delta
        if at + length > len(packet):
            raise ValueError("Truncated option")
        value = packet[at:at + length]; at += length
        if option == 4:
            result["etag"] = value
        elif option == 23:
            number = 0
            for byte in value:
                number = number * 256 + byte
            result["block"] = (number >> 4, bool(number & 8), number & 7)
    return result


def validate_response(result, mid, block=None, confirmable=False):
    if result["code"] != 69 or not result["payload"]:
        raise ValueError("Expected 2.05 content")
    if confirmable and (result["type"] != 2 or result["mid"] != mid):
        raise ValueError("Expected piggybacked ACK with matching MID")
    if not confirmable and result["type"] != 1:
        raise ValueError("Expected NON response")
    if block is not None and (result["block"] != (block, block < 31, 6) or
                              len(result["payload"]) != 1024 or not result["etag"]):
        raise ValueError("Invalid Block2 representation")
