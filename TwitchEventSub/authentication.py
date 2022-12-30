import threading
import time
import typing
import urllib.parse
import webbrowser
import logging

import requests
from flask import Flask, request

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


class InvalidTokenException(Exception):
    pass


def get_access_token(client_id: str, client_secret: str, scopes: typing.List[str]) -> typing.Dict[str, str]:
    result = {"ready": False}

    app = Flask(__name__)

    @app.route("/")
    def auth():
        r = requests.post(
            "https://id.twitch.tv/oauth2/token?"
            "client_id={}&client_secret={}&code={}&grant_type=authorization_code&redirect_uri={}".format(
                client_id, client_secret, request.args["code"], "http://localhost:5000"
            )
        )
        token_data = r.json()

        result["access_token"] = token_data["access_token"]
        result["refresh_token"] = token_data["refresh_token"]

        r = requests.get("https://api.twitch.tv/helix/users", headers={
            "Client-ID": client_id,
            "Authorization": "Bearer " + result["access_token"]
        })

        user_data = r.json()["data"][0]

        result["broadcaster_id"] = user_data["id"]
        result["broadcaster_login"] = user_data["login"]
        result["broadcaster_display_name"] = user_data["display_name"]
        result["ready"] = True

        return "Authentication complete. You may close this tab."

    flask_thread = threading.Thread(target=app.run, daemon=True, name="Twitch Auth Flask App")
    flask_thread.start()

    webbrowser.open(get_login_url(client_id, scopes))

    while result.get("ready", False) is False:
        time.sleep(0.1)

    try:
        del result["ready"]

    except KeyError:
        pass

    return result


def build_url(url: str, args: dict):
    return (url if url.endswith("?") else url + "?") + urllib.parse.urlencode(args)


def get_login_url(client_id: str, scopes: typing.List[str]) -> str:
    return build_url("https://id.twitch.tv/oauth2/authorize?", {
        "client_id": client_id,
        "scope": " ".join(scopes),
        "redirect_uri": "http://localhost:5000",
        "response_type": "code"
    })


def refresh_token(client_id: str, client_secret: str, refresh: str) -> typing.Tuple[str, str]:
    while True:
        try:
            r = requests.post(
                "https://id.twitch.tv/oauth2/token?"
                "client_id={}&client_secret={}&refresh_token={}&grant_type=refresh_token".format(
                    client_id, client_secret, refresh
                )
            )
            token_data = r.json()

            return token_data["access_token"], token_data["refresh_token"]

        except requests.ConnectionError:
            print("Retrying refresh token...")
            time.sleep(0.5)

        except KeyError:
            raise InvalidTokenException("Failed to authenticate. client_id, client_secret, or refresh token is invalid")
