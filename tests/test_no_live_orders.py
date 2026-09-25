"""Tests asserting zero order execution capability and strict safety boundaries."""
import unittest
from paper.broker import PaperBroker, OrderExecutionProhibitedError


class TestNoLiveOrders(unittest.TestCase):

    def test_paper_broker_blocks_live_orders(self):
        broker = PaperBroker()
        with self.assertRaises(OrderExecutionProhibitedError):
            broker.execute_live_order()

    def test_prohibits_credentials(self):
        broker = PaperBroker()
        self.assertFalse(hasattr(broker, "api_key"))
        self.assertFalse(hasattr(broker, "api_secret"))
        self.assertFalse(hasattr(broker, "private_key"))

    def test_prohibited_attribute_raises(self):
        class MaliciousBroker(PaperBroker):
            def __init__(self):
                self.api_key = "SECRET"
                super().__init__()

        with self.assertRaises(OrderExecutionProhibitedError):
            MaliciousBroker()


if __name__ == "__main__":
    unittest.main()
