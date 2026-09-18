from __future__ import annotations

from trainlab.contracts.errors import ErrorCode, ErrorEnvelope, failure_envelope

_MESSAGES = {
    ErrorCode.INVALID_ARGUMENT: "认证输入无效。",
    ErrorCode.RUN_BUSY: "认证操作正在进行，请稍后重试。",
    ErrorCode.SOURCE_CONFLICT: "认证已由其他操作更新，请重新开始。",
    ErrorCode.TIMEOUT: "认证操作或验证码流程已超时，请重新开始。",
    ErrorCode.CONFIG_UNAVAILABLE: "认证配置不可用，请检查环境或执行登录。",
    ErrorCode.DATA_INVALID: "认证数据格式无效，请重新登录。",
    ErrorCode.AUTH_REFRESH_REQUIRED: "认证未完成或需要人工登录，请重新开始登录。",
    ErrorCode.RESOURCE_LIMIT: "认证服务限流，请稍后重试。",
    ErrorCode.EXTERNAL_SERVICE_FAILED: "认证操作失败，未确认成功；请稍后重试。",
}


class GarminAuthError(ValueError):
    def __init__(self, code: ErrorCode, reason: str) -> None:
        self.code = code
        self.reason = reason
        self.message = "验证码验证未完成，请重新开始登录。" if reason == "mfa_verification_incomplete" else _MESSAGES[code]
        super().__init__(f"{code.value}: {self.message}")

    def envelope(self) -> ErrorEnvelope:
        return failure_envelope(self.code, self.message, {"reason": self.reason})
