import struct

import itch


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


def test_add_order():
    payload = struct.pack(
        ">cHH6sQcI8sI",
        b"A", 7, 100, (12345).to_bytes(6, "big"),
        555, b"B", 200, b"AAPL    ", 1500000,
    )
    msg = itch.decode(payload)
    check(msg["type"] == "A", "add order type")
    check(msg["stock_locate"] == 7, "add order stock_locate")
    check(msg["tracking_number"] == 100, "add order tracking_number")
    check(msg["timestamp"] == 12345, "add order timestamp")
    check(msg["order_ref"] == 555, "add order order_ref")
    check(msg["side"] == "B", "add order side")
    check(msg["shares"] == 200, "add order shares")
    check(msg["stock"] == "AAPL", "add order stock, padding stripped")
    check(msg["price"] == 1500000, "add order price stays raw fixed point")


def test_add_order_mpid():
    payload = struct.pack(
        ">cHH6sQcI8sI4s",
        b"F", 7, 100, (12345).to_bytes(6, "big"),
        556, b"S", 300, b"MSFT    ", 4200000, b"NSDQ",
    )
    msg = itch.decode(payload)
    check(msg["type"] == "F", "add order mpid type")
    check(msg["side"] == "S", "add order mpid side")
    check(msg["attribution"] == "NSDQ", "add order mpid attribution")


def test_order_executed():
    payload = struct.pack(
        ">cHH6sQIQ",
        b"E", 7, 101, (12400).to_bytes(6, "big"),
        555, 100, 999888,
    )
    msg = itch.decode(payload)
    check(msg["type"] == "E", "executed type")
    check(msg["executed_shares"] == 100, "executed shares")
    check(msg["match_number"] == 999888, "executed match number")


def test_order_executed_with_price():
    payload = struct.pack(
        ">cHH6sQIQcI",
        b"C", 7, 102, (12450).to_bytes(6, "big"),
        555, 50, 999889, b"Y", 1510000,
    )
    msg = itch.decode(payload)
    check(msg["type"] == "C", "executed with price type")
    check(msg["printable"] == "Y", "executed with price printable")
    check(msg["price"] == 1510000, "executed with price price")


def test_order_cancel():
    payload = struct.pack(
        ">cHH6sQI",
        b"X", 7, 103, (12500).to_bytes(6, "big"),
        555, 25,
    )
    msg = itch.decode(payload)
    check(msg["type"] == "X", "cancel type")
    check(msg["cancelled_shares"] == 25, "cancel shares")


def test_order_delete():
    payload = struct.pack(
        ">cHH6sQ",
        b"D", 7, 104, (12550).to_bytes(6, "big"),
        555,
    )
    msg = itch.decode(payload)
    check(msg["type"] == "D", "delete type")
    check(msg["order_ref"] == 555, "delete order_ref")


def test_order_replace():
    payload = struct.pack(
        ">cHH6sQQII",
        b"U", 7, 105, (12600).to_bytes(6, "big"),
        555, 777, 150, 1495000,
    )
    msg = itch.decode(payload)
    check(msg["type"] == "U", "replace type")
    check(msg["original_order_ref"] == 555, "replace original_order_ref")
    check(msg["new_order_ref"] == 777, "replace new_order_ref")
    check(msg["shares"] == 150, "replace shares")
    check(msg["price"] == 1495000, "replace price")


def test_short_payload_rejected():
    try:
        itch.decode(b"D" + b"\x00" * 5)
    except itch.DecodeError:
        print("ok  short payload rejected")
    else:
        raise AssertionError("short payload should have been rejected")


def test_unsupported_type_rejected():
    try:
        itch.decode(b"S" + b"\x00" * 11)
    except itch.DecodeError:
        print("ok  unsupported message type rejected")
    else:
        raise AssertionError("unsupported message type should have been rejected")


def test_iter_messages():
    delete_payload = struct.pack(
        ">cHH6sQ", b"D", 7, 104, (12550).to_bytes(6, "big"), 555,
    )
    cancel_payload = struct.pack(
        ">cHH6sQI", b"X", 7, 103, (12500).to_bytes(6, "big"), 555, 25,
    )
    stream = (
        len(delete_payload).to_bytes(2, "big") + delete_payload
        + len(cancel_payload).to_bytes(2, "big") + cancel_payload
    )
    msgs = list(itch.iter_messages(stream))
    check(len(msgs) == 2, "iter_messages yields two messages")
    check(msgs[0]["type"] == "D", "iter_messages first message type")
    check(msgs[1]["type"] == "X", "iter_messages second message type")


TESTS = [
    test_add_order,
    test_add_order_mpid,
    test_order_executed,
    test_order_executed_with_price,
    test_order_cancel,
    test_order_delete,
    test_order_replace,
    test_short_payload_rejected,
    test_unsupported_type_rejected,
    test_iter_messages,
]


def main():
    for test in TESTS:
        test()
    print(f"{len(TESTS)} test(s) passed")


if __name__ == "__main__":
    main()
