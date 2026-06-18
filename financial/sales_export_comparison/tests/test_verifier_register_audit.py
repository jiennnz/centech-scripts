import unittest

import pandas as pd

from financial.sales_export_comparison.stages.verifier import compute_store_day


def _empty_base_frames() -> dict[str, pd.DataFrame]:
    return {
        "st": pd.DataFrame(
            columns=["Store_ID", "Ticket_Number", "Tax_Exempt", "Ticket_Type_ID", "Status_ID", "Refund"]
        ),
        "sts": pd.DataFrame(
            columns=["Ticket_Number", "Category_ID", "Taxable_Amount", "Non_Taxable_Amount", "Total"]
        ),
        "pay": pd.DataFrame(
            columns=[
                "Ticket_Number",
                "Payment_Date",
                "Transaction_ID",
                "Tip_Paid",
                "Payment_Type_ID",
                "Payment_Name_ID",
                "Processing_Status_ID",
                "Name",
                "Tendered_Amount",
                "Change",
                "Tip_Amount",
                "_tlen",
            ]
        ),
        "txn": pd.DataFrame(
            columns=[
                "Store_ID",
                "Transaction_Date",
                "Transaction_Type_Name",
                "Amount",
                "Status",
                "Transaction_ID",
            ]
        ),
        "dj": pd.DataFrame(columns=["Store_Number", "Action", "Amount", "Comments"]),
        "store_ref": pd.DataFrame([{"Store_Number": "4071", "Store_ID": "2875"}]),
    }


class RegisterAuditSelectionTests(unittest.TestCase):
    def test_skips_self_cancelled_reaudit_rows(self) -> None:
        frames = _empty_base_frames()
        frames.update(
            {
                "txn": pd.DataFrame(
                [
                    {
                        "Store_ID": "2875",
                        "Transaction_Date": "2026-04-13 18:34:00",
                        "Transaction_Type_Name": "Register Audit",
                        "Amount": 377.0,
                        "Status": "Void",
                        "Transaction_ID": "1346",
                    },
                    {
                        "Store_ID": "2875",
                        "Transaction_Date": "2026-04-13 21:41:00",
                        "Transaction_Type_Name": "Register Audit",
                        "Amount": 338.0,
                        "Status": "Inserted",
                        "Transaction_ID": "1347",
                    },
                    {
                        "Store_ID": "2875",
                        "Transaction_Date": "2026-04-13 21:42:00",
                        "Transaction_Type_Name": "Register Audit",
                        "Amount": 395.0,
                        "Status": "Inserted",
                        "Transaction_ID": "1348",
                    },
                    {
                        "Store_ID": "2875",
                        "Transaction_Date": "2026-04-13 21:42:00",
                        "Transaction_Type_Name": "Register Audit",
                        "Amount": 378.0,
                        "Status": "Inserted",
                        "Transaction_ID": "1349",
                    },
                ]
                ),
                "dj": pd.DataFrame(
                [
                    {
                        "Store_Number": "4071",
                        "Action": "Register Audit",
                        "Amount": 338.0,
                        "Comments": "Register #1: Over/Short: 0.31",
                    },
                    {
                        "Store_Number": "4071",
                        "Action": "Register Audit",
                        "Amount": 395.0,
                        "Comments": "Register #1: Over/Short: 395.00",
                    },
                    {
                        "Store_Number": "4071",
                        "Action": "Register Audit",
                        "Amount": 378.0,
                        "Comments": "Register #1: Over/Short: 378.00",
                    },
                ]
                ),
            }
        )

        result = compute_store_day(4071, "2026-04-13", frames)
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["Register Audit"], (338.0, 0.0))
        self.assertEqual(rows["Cash Over/Short Adjustment"], (0.0, 0.31))


class CancelledTicketCategoryTests(unittest.TestCase):
    def test_status_2_ticket_is_excluded_from_tax_and_instore_credit_card(self) -> None:
        frames = _empty_base_frames()
        frames["st"] = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "ACTIVE",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "4",
                    "Refund": "False",
                },
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "CANCELLED",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "2",
                    "Refund": "False",
                },
            ]
        )
        frames["sts"] = pd.DataFrame(
            [
                {"Ticket_Number": "ACTIVE", "Category_ID": "1", "Taxable_Amount": 10.0, "Non_Taxable_Amount": 0.0, "Total": 10.0},
                {"Ticket_Number": "ACTIVE", "Category_ID": "5", "Taxable_Amount": 0.0, "Non_Taxable_Amount": 0.0, "Total": 1.0},
                {"Ticket_Number": "CANCELLED", "Category_ID": "1", "Taxable_Amount": 20.0, "Non_Taxable_Amount": 0.0, "Total": 20.0},
                {"Ticket_Number": "CANCELLED", "Category_ID": "5", "Taxable_Amount": 0.0, "Non_Taxable_Amount": 0.0, "Total": 2.0},
            ]
        )
        frames["pay"] = pd.DataFrame(
            [
                {
                    "Ticket_Number": "ACTIVE",
                    "Payment_Date": "2026-04-13 12:00:00",
                    "Transaction_ID": "123456",
                    "Tip_Paid": "True",
                    "Payment_Type_ID": "14",
                    "Payment_Name_ID": "",
                    "Processing_Status_ID": "4",
                    "Name": "",
                    "Tendered_Amount": 11.0,
                    "Change": 0.0,
                    "Tip_Amount": 0.0,
                    "_tlen": 6,
                },
                {
                    "Ticket_Number": "CANCELLED",
                    "Payment_Date": "2026-04-13 13:00:00",
                    "Transaction_ID": "654321",
                    "Tip_Paid": "True",
                    "Payment_Type_ID": "14",
                    "Payment_Name_ID": "",
                    "Processing_Status_ID": "4",
                    "Name": "",
                    "Tendered_Amount": 22.0,
                    "Change": 0.0,
                    "Tip_Amount": 0.0,
                    "_tlen": 6,
                },
            ]
        )

        result = compute_store_day(4071, "2026-04-13", frames)
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["Subject to Tax"], (0.0, 10.0))
        self.assertEqual(rows["Sales Tax"], (0.0, 1.0))
        self.assertEqual(rows["In-Store Credit Card"], (11.0, 0.0))


class CardProcessingStatusTests(unittest.TestCase):
    def test_processing_status_8_is_included_in_iscc_and_iscct(self) -> None:
        frames = _empty_base_frames()
        frames["st"] = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "STATUS8_A",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "False",
                },
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "STATUS8_B",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "False",
                },
            ]
        )
        frames["pay"] = pd.DataFrame(
            [
                {
                    "Ticket_Number": "STATUS8_A",
                    "Payment_Date": "2026-06-14 12:00:00",
                    "Transaction_ID": "1234",
                    "Tip_Paid": "True",
                    "Payment_Type_ID": "14",
                    "Payment_Name_ID": "",
                    "Processing_Status_ID": "8",
                    "Name": "",
                    "Tendered_Amount": 30.0,
                    "Change": 0.0,
                    "Tip_Amount": 2.50,
                    "_tlen": 4,
                },
                {
                    "Ticket_Number": "STATUS8_B",
                    "Payment_Date": "2026-06-14 12:15:00",
                    "Transaction_ID": "5678",
                    "Tip_Paid": "True",
                    "Payment_Type_ID": "14",
                    "Payment_Name_ID": "",
                    "Processing_Status_ID": "8",
                    "Name": "",
                    "Tendered_Amount": 17.36,
                    "Change": 0.0,
                    "Tip_Amount": 1.81,
                    "_tlen": 4,
                },
            ]
        )

        result = compute_store_day(4071, "2026-06-14", frames)
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["In-Store Credit Card"], (51.67, 0.0))
        self.assertEqual(round(rows["In-Store Credit Card Tips"][0], 2), 0.0)
        self.assertEqual(round(rows["In-Store Credit Card Tips"][1], 2), 4.31)


class CrossDateSalesAttributionTests(unittest.TestCase):
    def test_prior_folder_copy_is_excluded_when_business_date_has_refund_copy(self) -> None:
        frames = _empty_base_frames()
        frames["st"] = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "DUP_REFUND",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "True",
                },
            ]
        )
        frames["sts"] = pd.DataFrame(
            columns=["Ticket_Number", "Category_ID", "Taxable_Amount", "Non_Taxable_Amount", "Total"]
        )

        cross_date_st = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "DUP_REFUND",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "False",
                    "_source_pos_date": "2026-04-12",
                },
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "DUP_REFUND",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "True",
                    "_source_pos_date": "2026-04-13",
                },
            ]
        )
        cross_date_sts = pd.DataFrame(
            [
                {
                    "Ticket_Number": "DUP_REFUND",
                    "Category_ID": "1",
                    "Taxable_Amount": 32.30,
                    "Non_Taxable_Amount": 5.00,
                    "Total": 37.30,
                    "_source_pos_date": "2026-04-12",
                },
                {
                    "Ticket_Number": "DUP_REFUND",
                    "Category_ID": "5",
                    "Taxable_Amount": 0.0,
                    "Non_Taxable_Amount": 0.0,
                    "Total": 3.07,
                    "_source_pos_date": "2026-04-12",
                },
                {
                    "Ticket_Number": "DUP_REFUND",
                    "Category_ID": "1",
                    "Taxable_Amount": 21.40,
                    "Non_Taxable_Amount": 5.00,
                    "Total": 26.40,
                    "_source_pos_date": "2026-04-13",
                },
                {
                    "Ticket_Number": "DUP_REFUND",
                    "Category_ID": "5",
                    "Taxable_Amount": 0.0,
                    "Non_Taxable_Amount": 0.0,
                    "Total": 2.03,
                    "_source_pos_date": "2026-04-13",
                },
            ]
        )
        cross_date_pay = pd.DataFrame(
            [
                {
                    "Ticket_Number": "DUP_REFUND",
                    "Payment_Date": "2026-04-13 00:05:00",
                    "Transaction_ID": "cash",
                    "Tip_Paid": "False",
                    "Payment_Type_ID": "1",
                    "Payment_Name_ID": "",
                    "Processing_Status_ID": "4",
                    "Name": "",
                    "Tendered_Amount": 0.0,
                    "Change": 0.0,
                    "Tip_Amount": 0.0,
                    "_tlen": 4,
                },
            ]
        )

        result = compute_store_day(
            4071,
            "2026-04-13",
            frames,
            cross_date_pay=cross_date_pay,
            cross_date_sales=(cross_date_st, cross_date_sts),
        )
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["Subject to Tax"], (0.0, 21.40))
        self.assertEqual(rows["Non-Taxable Sales"], (0.0, 5.00))
        self.assertEqual(rows["Sales Tax"], (0.0, 2.03))

    def test_prior_folder_ticket_stays_included_without_business_date_refund_copy(self) -> None:
        frames = _empty_base_frames()
        frames["st"] = pd.DataFrame(
            columns=["Store_ID", "Ticket_Number", "Tax_Exempt", "Ticket_Type_ID", "Status_ID", "Refund"]
        )
        frames["sts"] = pd.DataFrame(
            columns=["Ticket_Number", "Category_ID", "Taxable_Amount", "Non_Taxable_Amount", "Total"]
        )

        cross_date_st = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "CROSS_MIDNIGHT",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "False",
                    "_source_pos_date": "2026-04-12",
                },
            ]
        )
        cross_date_sts = pd.DataFrame(
            [
                {
                    "Ticket_Number": "CROSS_MIDNIGHT",
                    "Category_ID": "1",
                    "Taxable_Amount": 12.00,
                    "Non_Taxable_Amount": 0.0,
                    "Total": 12.00,
                    "_source_pos_date": "2026-04-12",
                },
                {
                    "Ticket_Number": "CROSS_MIDNIGHT",
                    "Category_ID": "5",
                    "Taxable_Amount": 0.0,
                    "Non_Taxable_Amount": 0.0,
                    "Total": 1.14,
                    "_source_pos_date": "2026-04-12",
                },
            ]
        )
        cross_date_pay = pd.DataFrame(
            [
                {
                    "Ticket_Number": "CROSS_MIDNIGHT",
                    "Payment_Date": "2026-04-13 00:05:00",
                    "Transaction_ID": "cash",
                    "Tip_Paid": "False",
                    "Payment_Type_ID": "1",
                    "Payment_Name_ID": "",
                    "Processing_Status_ID": "4",
                    "Name": "",
                    "Tendered_Amount": 0.0,
                    "Change": 0.0,
                    "Tip_Amount": 0.0,
                    "_tlen": 4,
                },
            ]
        )

        result = compute_store_day(
            4071,
            "2026-04-13",
            frames,
            cross_date_pay=cross_date_pay,
            cross_date_sales=(cross_date_st, cross_date_sts),
        )
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["Subject to Tax"], (0.0, 12.00))
        self.assertEqual(rows["Sales Tax"], (0.0, 1.14))


class StoreTransactionCategoryTests(unittest.TestCase):
    def test_payin_void_rows_only_subtract_when_they_match_inserted_transaction(self) -> None:
        frames = _empty_base_frames()
        frames["txn"] = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Transaction_Date": "2026-06-12 10:00:00",
                    "Transaction_Type_Name": "Payins",
                    "Amount": 443.0,
                    "Status": "Inserted",
                    "Transaction_ID": "payin_inserted",
                },
                {
                    "Store_ID": "2875",
                    "Transaction_Date": "2026-06-12 11:00:00",
                    "Transaction_Type_Name": "Payins",
                    "Amount": 373.0,
                    "Status": "Void",
                    "Transaction_ID": "payin_void",
                },
                {
                    "Store_ID": "2875",
                    "Transaction_Date": "2026-06-12 12:00:00",
                    "Transaction_Type_Name": "Payins",
                    "Amount": 25.0,
                    "Status": "Inserted",
                    "Transaction_ID": "voided_payin",
                },
                {
                    "Store_ID": "2875",
                    "Transaction_Date": "2026-06-12 12:05:00",
                    "Transaction_Type_Name": "Payins",
                    "Amount": 25.0,
                    "Status": "Void",
                    "Transaction_ID": "voided_payin",
                },
            ]
        )

        result = compute_store_day(4071, "2026-06-12", frames)
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["Payin"], (0.0, 443.0))


class CardTicketTypeClassificationTests(unittest.TestCase):
    def test_walk_in_tlen32_refund_stays_instore_credit_card(self) -> None:
        frames = _empty_base_frames()
        frames["st"] = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "WALKIN_REFUND",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "1",
                    "Status_ID": "1",
                    "Refund": "True",
                },
            ]
        )
        frames["pay"] = pd.DataFrame(
            [
                {
                    "Ticket_Number": "WALKIN_REFUND",
                    "Payment_Date": "2026-04-13 12:00:00",
                    "Transaction_ID": "a" * 32,
                    "Tip_Paid": "True",
                    "Payment_Type_ID": "14",
                    "Payment_Name_ID": "1",
                    "Processing_Status_ID": "4",
                    "Name": "",
                    "Tendered_Amount": -397.94,
                    "Change": 0.0,
                    "Tip_Amount": 0.0,
                    "_tlen": 32,
                },
            ]
        )

        result = compute_store_day(4071, "2026-04-13", frames)
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["In-Store Credit Card"], (-397.94, 0.0))
        self.assertEqual(rows["Online Credit card"], (0.0, 0.0))

    def test_online_tlen32_refund_stays_online_credit_card(self) -> None:
        frames = _empty_base_frames()
        frames["st"] = pd.DataFrame(
            [
                {
                    "Store_ID": "2875",
                    "Ticket_Number": "ONLINE_REFUND",
                    "Tax_Exempt": "False",
                    "Ticket_Type_ID": "5",
                    "Status_ID": "1",
                    "Refund": "True",
                },
            ]
        )
        frames["pay"] = pd.DataFrame(
            [
                {
                    "Ticket_Number": "ONLINE_REFUND",
                    "Payment_Date": "2026-04-13 12:00:00",
                    "Transaction_ID": "b" * 32,
                    "Tip_Paid": "True",
                    "Payment_Type_ID": "14",
                    "Payment_Name_ID": "1",
                    "Processing_Status_ID": "4",
                    "Name": "",
                    "Tendered_Amount": -20.0,
                    "Change": 0.0,
                    "Tip_Amount": 0.0,
                    "_tlen": 32,
                },
            ]
        )

        result = compute_store_day(4071, "2026-04-13", frames)
        self.assertIsNotNone(result)

        rows = {category: (debit, credit) for category, debit, credit in result}
        self.assertEqual(rows["In-Store Credit Card"], (0.0, 0.0))
        self.assertEqual(rows["Online Credit card"], (-20.0, 0.0))


if __name__ == "__main__":
    unittest.main()
