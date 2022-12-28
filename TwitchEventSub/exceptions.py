class TwitchEventSubException(Exception):
    pass


class FailedToSubscribeException(TwitchEventSubException):
    pass
