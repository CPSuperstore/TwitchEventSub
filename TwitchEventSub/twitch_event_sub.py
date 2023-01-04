import datetime
import threading
import typing
import json
import requests
import asyncio
import websockets
import abc
import hashlib
import logging

import TwitchEventSub.event_types.event_types as event_types
import TwitchEventSub.event_types.event_scopes as event_scopes
import TwitchEventSub.event_types.event_versions as event_versions
import TwitchEventSub.authentication as authentication
import TwitchEventSub.exceptions as exceptions


class TwitchEventSub(abc.ABC):
    def __init__(
            self, client_id: str, client_secret: str, subscribed_events: typing.List[event_types.EventType],
            additional_scopes: typing.List[str] = None,
            persist_credentials: bool = True, credentials_path: str = "salts.json",
            ws_url: str = 'wss://eventsub-beta.wss.twitch.tv/ws'
    ):
        if additional_scopes is None:
            additional_scopes = []

        self._client_id = client_id
        self._client_secret = client_secret
        self._persist_credentials = persist_credentials
        self._ws_url = ws_url
        self._subscribed_events = subscribed_events
        self._credentials_path = credentials_path
        self._additional_scopes = additional_scopes

        self._access_token = None
        self._refresh_token = None
        self._broadcaster_id = None
        self._broadcaster_login = None
        self._broadcaster_display_name = None

        self._received_message_ids = []

        self._session_id = None

        self._logger = logging.getLogger("TwitchEventSub")
        self._logger.setLevel(logging.INFO)

        self._logger.info("Building list of authentication scopes...")
        self._scopes = [
            event_scopes.EVENT_SCOPES.get(scope, None) for scope in subscribed_events
            if event_scopes.EVENT_SCOPES.get(scope, None) is not None
        ]

        self._scopes.extend(additional_scopes)

        self._scopes = list(set(self._scopes))
        self._scopes.sort()

        self._logger.info("Configuration requires {} scope(s)".format(len(self._scopes)))

        self._event_type_register = {
            event_types.EventType.CHANNEL_UPDATE: self.on_channel_update,
            event_types.EventType.CHANNEL_FOLLOW: self.on_channel_follow,
            event_types.EventType.CHANNEL_SUBSCRIBE: self.on_channel_subscribe,
            event_types.EventType.CHANNEL_SUBSCRIPTION_END: self.on_channel_subscription_end,
            event_types.EventType.CHANNEL_SUBSCRIPTION_GIFT: self.on_channel_subscription_gift,
            event_types.EventType.CHANNEL_SUBSCRIPTION_MESSAGE: self.on_channel_subscription_message,
            event_types.EventType.CHANNEL_CHEER: self.on_channel_cheer,
            event_types.EventType.CHANNEL_RAID: self.on_channel_raid,
            event_types.EventType.CHANNEL_BAN: self.on_channel_ban,
            event_types.EventType.CHANNEL_UNBAN: self.on_channel_unban,
            event_types.EventType.CHANNEL_MODERATOR_ADD: self.on_channel_moderator_add,
            event_types.EventType.CHANNEL_MODERATOR_REMOVE: self.on_channel_moderator_remove,
            event_types.EventType.CHANNEL_POINTS_CUSTOM_REWARD_ADD: self.on_channel_points_custom_reward_add,
            event_types.EventType.CHANNEL_POINTS_CUSTOM_REWARD_UPDATE: self.on_channel_points_custom_reward_update,
            event_types.EventType.CHANNEL_POINTS_CUSTOM_REWARD_REMOVE: self.on_channel_points_custom_reward_remove,
            event_types.EventType.CHANNEL_POINTS_CUSTOM_REWARD_REDEMPTION_ADD:
                self.on_channel_points_custom_reward_redemption_add,
            event_types.EventType.CHANNEL_POINTS_CUSTOM_REWARD_REDEMPTION_UPDATE:
                self.on_channel_points_custom_reward_redemption_update,
            event_types.EventType.CHANNEL_POLL_BEGIN: self.on_channel_poll_begin,
            event_types.EventType.CHANNEL_POLL_PROGRESS: self.on_channel_poll_progress,
            event_types.EventType.CHANNEL_POLL_END: self.on_channel_poll_end,
            event_types.EventType.CHANNEL_PREDICTION_BEGIN: self.on_channel_prediction_begin,
            event_types.EventType.CHANNEL_PREDICTION_PROGRESS: self.on_channel_prediction_progress,
            event_types.EventType.CHANNEL_PREDICTION_LOCK: self.on_channel_prediction_lock,
            event_types.EventType.CHANNEL_PREDICTION_END: self.on_channel_prediction_end,
            event_types.EventType.CHARITY_DONATION: self.on_charity_donation,
            event_types.EventType.CHARITY_CAMPAIGN_START: self.on_charity_campaign_start,
            event_types.EventType.CHARITY_CAMPAIGN_PROGRESS: self.on_charity_campaign_progress,
            event_types.EventType.CHARITY_CAMPAIGN_STOP: self.on_charity_campaign_stop,
            event_types.EventType.DROP_ENTITLEMENT_GRANT: self.on_drop_entitlement_grant,
            event_types.EventType.EXTENSION_BITS_TRANSACTION_CREATE: self.on_extension_bits_transaction_create,
            event_types.EventType.GOAL_BEGIN: self.on_goal_begin,
            event_types.EventType.GOAL_PROGRESS: self.on_goal_progress,
            event_types.EventType.GOAL_END: self.on_goal_end,
            event_types.EventType.HYPE_TRAIN_BEGIN: self.on_hype_train_begin,
            event_types.EventType.HYPE_TRAIN_PROGRESS: self.on_hype_train_progress,
            event_types.EventType.HYPE_TRAIN_END: self.on_hype_train_end,
            event_types.EventType.SHIELD_MODE_BEGIN: self.on_shield_mode_begin,
            event_types.EventType.SHIELD_MODE_END: self.on_shield_mode_end,
            event_types.EventType.STREAM_ONLINE: self.on_stream_online,
            event_types.EventType.STREAM_OFFLINE: self.on_stream_offline,
            event_types.EventType.USER_AUTHORIZATION_GRANT: self.on_user_authorization_grant,
            event_types.EventType.USER_AUTHORIZATION_REVOKE: self.on_user_authorization_revoke,
            event_types.EventType.USER_UPDATE: self.on_user_update,
        }

    def _dump_credentials(self):
        if not self._persist_credentials:
            return

        logging.info("Dumping refresh token to '{}' to persist it...".format(self._credentials_path))

        with open(self._credentials_path, 'w') as f:
            f.write(json.dumps(dict(
                # access_token=self._access_token,
                refresh_token=self._refresh_token,
                broadcaster_id=self._broadcaster_id,
                broadcaster_login=self._broadcaster_login,
                broadcaster_display_name=self._broadcaster_display_name,
                scope_hash=self._get_scope_hash()
            )))

    def _get_scope_hash(self) -> str:
        return hashlib.sha3_256(" ".join(self._scopes).encode("UTF-8")).hexdigest()

    def _restore_credentials(self) -> bool:
        self._logger.info("Attempting to restore persisted credentials from '{}'".format(self._credentials_path))

        try:
            with open(self._credentials_path) as f:
                data = json.loads(f.read())

            # self._access_token = data["access_token"]
            self._refresh_token = data["refresh_token"]
            self._broadcaster_id = data["broadcaster_id"]
            self._broadcaster_login = data["broadcaster_login"]
            self._broadcaster_display_name = data["broadcaster_display_name"]

            if data["scope_hash"] != self._get_scope_hash():
                self._logger.warning(
                    "The list of scopes have changed since last authentication. Credentials can not be persisted!"
                )
                return False

        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            self._logger.warning(
                "Either the persistent credentials file is missing or in an invalid format. "
                "Credentials can not be persisted!"
            )
            return False

        self._logger.info("Validating persisted credentials")
        return self.refresh_token()

    def authenticate(self):
        if self._persist_credentials:
            if self._restore_credentials():
                self._logger.info("Persisted credentials have been restored")
                return

            self._logger.warning("Persisted credentials could not be restored")

        self._logger.info("Obtaining a new access token...")
        result = authentication.get_access_token(self._client_id, self._client_secret, self._scopes)

        self._access_token = result["access_token"]
        self._refresh_token = result["refresh_token"]
        self._broadcaster_id = result["broadcaster_id"]
        self._broadcaster_login = result["broadcaster_login"]
        self._broadcaster_display_name = result["broadcaster_display_name"]

        self._dump_credentials()

    def refresh_token(self) -> bool:
        try:
            self._access_token, self._refresh_token = authentication.refresh_token(
                self._client_id, self._client_secret, self._refresh_token
            )

        except authentication.InvalidTokenException:
            logging.warning("Failed to validate token. Manual authentication is needed")
            return False

        self._dump_credentials()

        return True

    def send_api_request(self, endpoint: str, method: str, params: dict = None, body: dict = None) -> requests.Response:
        args = locals()

        if body is None:
            body = {}

        if params is None:
            params = {}

        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        r = requests.request(
            method, "https://api.twitch.tv" + endpoint,
            headers={
                "Authorization": "Bearer {}".format(self._access_token),
                "Client-Id": self._client_id
            },
            params=params, json=body
        )

        if r.status_code == 401:
            logging.warning("Access token has expired. Refreshing and resending request...")
            self.refresh_token()

            return self.send_api_request(**args)

        return r

    def _add_subscription(self, sub_type: event_types.EventType):
        logging.info("Subscribing to websocket event {}".format(sub_type.value))

        r = self.send_api_request("/helix/eventsub/subscriptions", "POST", body={
            "type": sub_type.value,
            "version": event_versions.EVENT_VERSIONS[sub_type],
            "condition": {"broadcaster_user_id": str(self._broadcaster_id)},
            "transport": {"method": "websocket", "session_id": self._session_id}
        })

        if r.status_code != 202:
            logging.error("Failed to subscribe to websocket event {}".format(sub_type.value))
            raise exceptions.FailedToSubscribeException(r.json()["message"])

    async def _websocket_handler(self, websocket):
        logging.info("Websocket handler thread starting...")

        while True:
            packet = await websocket.recv()
            logging.debug("Received packet {}".format(packet))

            message: dict = json.loads(packet)

            metadata = message.get("metadata", {})

            message_type = metadata.get("message_type", None)
            subscription_type = metadata.get("subscription_type", None)

            if message_type == "session_welcome":
                logging.info("Received welcome message")

                self._session_id = message["payload"]["session"]["id"]

                logging.info("Subscribing to requested events")
                for sub in self._subscribed_events:
                    self._add_subscription(sub)

                logging.info("Ready to receive events from the websocket server")

            elif message_type == "notification":
                message_id = metadata.get("message_id", None)

                if message_id in self._received_message_ids or message_id is None:
                    logging.warning("Message with ID '{}' has already been received. Skipping it...".format(message_id))
                    continue

                try:
                    message_timestamp = metadata.get("message_timestamp", "")
                    message_timestamp = message_timestamp[:message_timestamp.index(".")]
                    timestamp = datetime.datetime.fromisoformat(message_timestamp)
                except ValueError:
                    logging.warning("Message with ID '{}' has invalid timestamp. Skipping it...".format(message_id))
                    continue

                if timestamp - datetime.datetime.utcnow() > datetime.timedelta(minutes=10):
                    logging.warning("Message with ID '{}' is too old to accept. Skipping it...".format(message_id))
                    continue

                self._received_message_ids.append(message_id)

                payload = message.get("payload")

                self.on_event(
                    event_types.EventType(subscription_type),
                    payload.get("event", {}),
                    payload.get("subscription", {}),
                    metadata
                )

    def on_event(self, event_type, event: dict, subscription: dict, metadata: dict):
        logging.info("Received event type {}".format(event_type.value))
        self._event_type_register[event_type](event, subscription, metadata)

    async def _start_ws_listener(self, reconnect: bool = True):
        logging.info("Starting websocket listener...")
        while True:
            try:
                logging.info("Establishing connection to websocket server...")
                async with websockets.connect(self._ws_url) as ws:

                    logging.info("Connection succeeded. Starting up websocket handler...")
                    await self._websocket_handler(ws)
                    await asyncio.Future()

            except websockets.ConnectionClosedError as e:
                if not reconnect:
                    logging.error(
                        "Connection to websocket server closed! Passing on exception... "
                        "(set reconnect=True in start method to attempt reconnection)"
                    )
                    raise e

                logging.error(
                    "Connection to websocket server closed! Retrying..."
                    "(set reconnect=False in start method to raise an exception instead)"
                )
                self.refresh_token()

    def start(self, reconnect: bool = True):
        if self._access_token is None:
            self.authenticate()

        # self.refresh_token()

        asyncio.run(self._start_ws_listener(reconnect))

    def start_thread(
            self, reconnect: bool = True, thread_name: str = "TwitchEventSubHandlerThread", daemon: bool = True
    ) -> threading.Thread:

        t = threading.Thread(target=self.start, args=[reconnect], daemon=daemon, name=thread_name)
        t.start()
        return t

    def on_channel_update(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_follow(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_subscribe(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_subscription_end(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_subscription_gift(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_subscription_message(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_cheer(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_raid(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_ban(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_unban(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_moderator_add(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_moderator_remove(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_points_custom_reward_add(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_points_custom_reward_update(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_points_custom_reward_remove(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_points_custom_reward_redemption_add(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_points_custom_reward_redemption_update(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_poll_begin(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_poll_progress(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_poll_end(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_prediction_begin(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_prediction_progress(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_prediction_lock(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_channel_prediction_end(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_charity_donation(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_charity_campaign_start(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_charity_campaign_progress(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_charity_campaign_stop(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_drop_entitlement_grant(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_extension_bits_transaction_create(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_goal_begin(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_goal_progress(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_goal_end(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_hype_train_begin(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_hype_train_progress(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_hype_train_end(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_shield_mode_begin(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_shield_mode_end(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_stream_online(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_stream_offline(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_user_authorization_grant(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_user_authorization_revoke(self, event: dict, subscription: dict, metadata: dict):
        pass

    def on_user_update(self, event: dict, subscription: dict, metadata: dict):
        pass
