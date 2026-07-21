class ProviderError(Exception):
    def __init__(self, code: str, message: str, *, provider: str, operation: str,
                 retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider = provider
        self.operation = operation
        self.retryable = retryable
        self.status_code = status_code


class ProviderCancelledError(ProviderError):
    pass
