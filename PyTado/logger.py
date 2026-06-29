"""Custom logger for PyTado."""

import logging


class Logger(logging.Logger):
    """Custom logger without masking sensitive information."""

    class SimpleFormatter(logging.Formatter):
        """Simple formatter."""

    def __init__(self, name: str, level=logging.NOTSET):
        super().__init__(name)
        log_sh = logging.StreamHandler()
        log_fmt = self.SimpleFormatter(fmt="%(name)s :: %(levelname)-8s :: %(message)s")
        log_sh.setFormatter(log_fmt)
        self.addHandler(log_sh)
        self.setLevel(level)
