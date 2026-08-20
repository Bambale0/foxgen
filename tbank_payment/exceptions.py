"""Исключения для T-Bank API"""


class TBankException(Exception):
    """Базовое исключение T-Bank"""


class TBankAPIError(TBankException):
    """Ошибка API Т-Банка"""

    def __init__(self, message: str, error_code: str = None):
        super().__init__(f"T-Bank API error {error_code}: {message}")
        self.error_code = error_code
        self.message = message


class TBankNetworkError(TBankException):
    """Сетевая ошибка"""


class TBankAuthError(TBankAPIError):
    """Ошибка аутентификации"""


class TBankValidationError(TBankAPIError):
    """Ошибка валидации запроса"""


class TBankPaymentError(TBankException):
    """Ошибка платежа"""
