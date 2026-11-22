class AppError(Exception):
    """An error safe to display to the user."""


class Cancelled(AppError):
    pass
