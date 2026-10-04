import pandas as pd

from opspulse.etl.transform import stage_table
from opspulse.etl.validate import validate_rows


def raw_frame(**columns) -> pd.DataFrame:
    return pd.DataFrame({name: [value] for name, value in columns.items()}, dtype="str")


def test_codes_stay_text_state_is_normalized_city_is_untouched():
    raw = raw_frame(
        customer_id="c",
        customer_unique_id="u",
        customer_zip_code_prefix="01037",
        customer_city=" São Paulo ",
        customer_state=" sp ",
    )

    staged = stage_table("customers", raw)

    assert staged.loc[0, "zip_code_prefix"] == "01037"
    assert staged.loc[0, "city"] == "São Paulo"
    assert staged.loc[0, "state"] == "SP"


def test_product_typos_get_canonical_names():
    raw = raw_frame(
        product_id="p",
        product_category_name="perfumaria",
        product_name_lenght="40",
        product_description_lenght="287",
        product_photos_qty="1",
        product_weight_g="225",
        product_length_cm="16",
        product_height_cm="10",
        product_width_cm="14",
    )

    staged = stage_table("products", raw)

    assert staged.loc[0, "name_length"] == 40
    assert staged.loc[0, "description_length"] == 287
    assert "product_name_lenght" not in staged.columns


def test_unparseable_values_become_null_and_are_reported():
    raw = raw_frame(
        order_id="a" * 32,
        order_item_id="1.5",
        product_id="b" * 32,
        seller_id="d" * 32,
        shipping_limit_date="2017-02-30 10:00:00",
        price="abc",
        freight_value="10.00",
    )

    staged = stage_table("order_items", raw)
    issues = validate_rows({"order_items": staged}, {"order_items": raw})

    assert staged.loc[0, ["order_item_id", "shipping_limit_at", "price"]].isna().all()
    assert {"INVALID_ORDER_ITEM_ID", "INVALID_SHIPPING_LIMIT_AT", "INVALID_PRICE"} <= set(
        issues["code"]
    )
