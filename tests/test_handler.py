import unittest
import sys
import json

sys.path.append('..')

from TwitchEventSub import *

with open("../credentials.json") as f:
    credentials = json.loads(f.read())


class TestCaseHandler(unittest.TestCase):
    def test_channel_point_redemption(self):
        class Handler(TwitchEventSub):
            def on_channel_points_custom_reward_redemption_add(self, event: dict, subscription: dict, metadata: dict):
                print(event)

        bot = Handler(
            credentials["client_id"], credentials["client_secret"],
            [EventType.CHANNEL_POINTS_CUSTOM_REWARD_REDEMPTION_ADD]
        )

        bot.start()


if __name__ == '__main__':
    unittest.main()
