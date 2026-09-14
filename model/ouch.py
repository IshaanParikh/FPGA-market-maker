# OUCH 5.0 encoder, core fields only: Enter Order (O), Replace Order (U),
# Cancel Order (X), the three messages a market maker sends to place,
# reprice, or pull a quote. Each message here is the fixed, required part
# of the real message plus a trailing zero length Appendage Length field.
# OUCH 5.0 also supports an optional block of extra settings appended
# after that (minimum quantity, discretionary price, and so on); this
# does not implement it, so every message here uses OUCH's own defaults
# for everything left unset, which is a fully valid message on its own.
#
# Numeric fields are big-endian, matching the spec's data types section.
# Price is 8 bytes here with 4 implied decimal digits, wider than ITCH's
# 4 byte Price field.

import struct


def encode_enter_order(user_ref_num, side, quantity, symbol, price,
                        time_in_force="0", display="Y", capacity="A",
                        iso_eligible="N", cross_type="N", clordid=""):
    return struct.pack(
        ">cIcI8sQccccc14sH",
        b"O", user_ref_num, side.encode(), quantity, symbol.encode().ljust(8),
        price, time_in_force.encode(), display.encode(), capacity.encode(),
        iso_eligible.encode(), cross_type.encode(), clordid.encode().ljust(14),
        0,
    )


def encode_replace_order(orig_user_ref_num, user_ref_num, quantity, price,
                          time_in_force="0", display="Y", iso_eligible="N", clordid=""):
    return struct.pack(
        ">cIIIQccc14sH",
        b"U", orig_user_ref_num, user_ref_num, quantity, price,
        time_in_force.encode(), display.encode(), iso_eligible.encode(),
        clordid.encode().ljust(14), 0,
    )


def encode_cancel_order(user_ref_num, quantity):
    return struct.pack(">cIIH", b"X", user_ref_num, quantity, 0)


def frame(payload):
    length = len(payload)
    return bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload
