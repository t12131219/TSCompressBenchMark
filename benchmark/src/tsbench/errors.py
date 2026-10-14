class BenchError(RuntimeError):
    status = "error"
    def __init__(self, message, *, stage="codec"):
        super().__init__(message)
        self.stage = stage

class Unsupported(BenchError):
    status = "unsupported"

class Unavailable(BenchError):
    status = "unavailable"

class ValidationError(BenchError):
    pass
