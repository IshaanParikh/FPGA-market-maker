# A simple order book for one stock, kept as a dictionary of resting
# orders keyed by order ID. Applying a message returns whether it was
# accepted, and the best bid and best ask afterward.


class OrderBook:
    def __init__(self, capacity=64):
        self.capacity = capacity
        self.orders = {}

    def _best(self, side):
        resting = [o for o in self.orders.values() if o["side"] == side]
        if not resting:
            return None, 0
        if side == "B":
            best_price = max(o["price"] for o in resting)
        else:
            best_price = min(o["price"] for o in resting)
        qty = sum(o["shares"] for o in resting if o["price"] == best_price)
        return best_price, qty

    def apply(self, msg):
        """Apply one decoded ITCH message (same shape as itch.decode()'s
        output). Returns (err, (bid_price, bid_qty), (ask_price, ask_qty)).
        A price of None means that side of the book is empty."""
        mtype = msg["type"]
        err = False

        if mtype in ("A", "F"):
            if len(self.orders) >= self.capacity:
                err = True
            else:
                self.orders[msg["order_ref"]] = {
                    "side": msg["side"],
                    "price": msg["price"],
                    "shares": msg["shares"],
                }

        elif mtype in ("E", "C"):
            order = self.orders.get(msg["order_ref"])
            if order is None:
                err = True
            elif order["shares"] - msg["executed_shares"] <= 0:
                del self.orders[msg["order_ref"]]
            else:
                order["shares"] -= msg["executed_shares"]

        elif mtype == "X":
            order = self.orders.get(msg["order_ref"])
            if order is None:
                err = True
            elif order["shares"] - msg["cancelled_shares"] <= 0:
                del self.orders[msg["order_ref"]]
            else:
                order["shares"] -= msg["cancelled_shares"]

        elif mtype == "D":
            if msg["order_ref"] in self.orders:
                del self.orders[msg["order_ref"]]
            else:
                err = True

        elif mtype == "U":
            # a replace never says which side the order is on, so carry
            # the side over from the order being replaced
            order = self.orders.get(msg["original_order_ref"])
            if order is None:
                err = True
            else:
                del self.orders[msg["original_order_ref"]]
                self.orders[msg["new_order_ref"]] = {
                    "side": order["side"],
                    "price": msg["price"],
                    "shares": msg["shares"],
                }

        else:
            err = True

        return err, self._best("B"), self._best("S")
