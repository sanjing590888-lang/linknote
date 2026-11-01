"""统一错误类型。每个错误都带阶段（stage），方便定位阻塞点。"""


class LinknoteError(Exception):
    """所有可预期失败的基类。stage 表示失败发生在哪一步。"""

    stage = "unknown"
    code = "error"

    def __init__(self, message, *, stage=None, code=None, hint=None, partial=None):
        super().__init__(message)
        self.message = message
        if stage:
            self.stage = stage
        if code:
            self.code = code
        self.hint = hint or ""
        # partial: 已经成功产出的中间结果（路径/说明），失败时仍会写进笔记
        self.partial = partial or []


class UnsupportedLink(LinknoteError):
    stage = "normalize"
    code = "unsupported_link"


class InvalidLink(LinknoteError):
    stage = "normalize"
    code = "invalid_link"


class NotAccessible(LinknoteError):
    stage = "fetch"
    code = "not_accessible"


class LoginRequired(LinknoteError):
    stage = "fetch"
    code = "login_required"


class RateLimited(LinknoteError):
    stage = "fetch"
    code = "rate_limited"


class NetworkFailure(LinknoteError):
    stage = "fetch"
    code = "network_failure"


class TranscribeFailure(LinknoteError):
    stage = "transcribe"
    code = "transcribe_failed"


class TranscribeNotConfigured(LinknoteError):
    stage = "transcribe"
    code = "transcribe_not_configured"


class OutputNotWritable(LinknoteError):
    stage = "export"
    code = "output_not_writable"
