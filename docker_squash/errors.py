class Error(Exception):
    pass


class SquashError(Error):
    code = 1


class SquashUnnecessaryError(SquashError):
    code = 2
