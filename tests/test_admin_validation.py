import pytest

from foxgen.admin.content_service import AdminNotificationService
from foxgen.admin.errors import AdminValidationError
from foxgen.admin.finance_service import AdminTariffService
from foxgen.bot.admin import admin_main_keyboard


def test_tariff_validation_rejects_unknown_and_negative_values() -> None:
    AdminTariffService._validate_payload(
        {
            "packages": {"starter": {"credits": 1000, "price": 500}},
            "model_prices": {"seedream-5-pro": 250},
        }
    )

    with pytest.raises(AdminValidationError):
        AdminTariffService._validate_payload({"unknown": {}})
    with pytest.raises(AdminValidationError):
        AdminTariffService._validate_payload({"packages": {"starter": {"price": -1}}})


def test_model_price_validation_requires_positive_integer_credit_amounts() -> None:
    assert AdminTariffService._validated_model_prices(
        {
            "image_prices": {"seedream-5-pro": 200},
            "video_prices": {"seedance-2": 500},
        }
    ) == {"seedream-5-pro": 200, "seedance-2": 500}

    with pytest.raises(AdminValidationError):
        AdminTariffService._validated_model_prices({"model_prices": {"x": 0}})
    with pytest.raises(AdminValidationError):
        AdminTariffService._validated_model_prices({"model_prices": {"x": 1.5}})


def test_campaign_segment_validation_is_explicit_and_bounded() -> None:
    AdminNotificationService._validate_segment(
        {
            "user_ids": [1, 2, 3],
            "created_after": "2026-08-01T00:00:00+00:00",
        }
    )
    with pytest.raises(AdminValidationError):
        AdminNotificationService._validate_segment({"country": "RU"})
    with pytest.raises(AdminValidationError):
        AdminNotificationService._validate_segment({"user_ids": [1, "2"]})


def test_admin_main_keyboard_callbacks_fit_telegram_limit() -> None:
    keyboard = admin_main_keyboard()
    for row in keyboard.inline_keyboard:
        for button in row:
            if button.callback_data is not None:
                assert len(button.callback_data.encode("utf-8")) <= 64
