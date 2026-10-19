
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import httpx


FRANKFURTER_API = "https://api.frankfurter.dev/v2"


async def convert_currency(
    amount: float,
    from_currency: str,
    to_currency: str,
) -> dict:
    """
    Convert an amount using the latest available
    Frankfurter exchange rate.

    Example:
    convert_currency(150, "GBP", "INR")
    """

    source = from_currency.strip().upper()
    target = to_currency.strip().upper()

    if not re.fullmatch(r"[A-Z]{3}", source):
        return {
            "status": "error",
            "message": "Invalid source currency code.",
        }

    if not re.fullmatch(r"[A-Z]{3}", target):
        return {
            "status": "error",
            "message": "Invalid target currency code.",
        }

    try:
        value = Decimal(str(amount))

        if not value.is_finite() or value < 0:
            raise InvalidOperation

    except (InvalidOperation, ValueError):
        return {
            "status": "error",
            "message": "Amount must be a non-negative number.",
        }

    if source == target:
        return {
            "status": "success",
            "amount": str(value),
            "from_currency": source,
            "to_currency": target,
            "exchange_rate": "1",
            "converted_amount": str(value),
            "rate_date": None,
            "provider": "Identity conversion",
        }

    url = f"{FRANKFURTER_API}/rate/{source}/{target}"

    try:
        async with httpx.AsyncClient(
            timeout=15.0
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        rate = Decimal(str(data["rate"]))

        if not rate.is_finite() or rate <= 0:
            raise ValueError("Invalid exchange rate.")

        converted_amount = (
            value * rate
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        return {
            "status": "success",
            "amount": str(value),
            "from_currency": source,
            "to_currency": target,
            "exchange_rate": str(rate),
            "converted_amount": str(converted_amount),
            "rate_date": data.get("date"),
            "provider": "Frankfurter",
        }

    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code

        if status_code in (400, 404, 422):
            message = (
                "Unsupported currency or exchange-rate pair."
            )
        else:
            message = (
                "Exchange-rate provider returned an error."
            )

        return {
            "status": "error",
            "message": message,
            "http_status": status_code,
        }

    except (
        httpx.RequestError,
        ValueError,
        KeyError,
        InvalidOperation,
    ):
        return {
            "status": "error",
            "message": (
                "Unable to retrieve a valid exchange rate. "
                "Please try again later."
            ),
        }
