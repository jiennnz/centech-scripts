"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { scrapeCsdPage, toComparisonRows } = require("../src/financial/csd");

test("extracts only CSD financial aggregates", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.setContent(`
    <input id="parameters:store" value="2006">
    <input id="parameters:startDateCalendarInputDate" value="06/29/2026">
    <table id="salesBreakdown"><tbody>
      <tr><td>Taxable Sales</td><td>163.25</td></tr>
      <tr><td>Non-Taxable Sales</td><td>3,703.77</td></tr>
      <tr><td>Tax Exempt Sales</td><td>0.0</td></tr>
      <tr><td>3rd Party Tax Exempt Sales</td><td>25.74</td></tr>
      <tr><td>Sales Tax</td><td>11.35</td></tr>
      <tr><td>Remote Payment</td><td>0.00</td></tr>
    </tbody></table>
    <table id="bankBreakdown"><tbody>
      <tr><td>Register Audit(CID)</td><td></td><td></td><td>339.70</td><td></td></tr>
    </tbody></table>
    <table id="registerAudit"><thead><tr>
      <th>Time</th><th>Type</th><th>Amount</th><th>Employee</th><th>Comment</th>
    </tr></thead><tbody><tr>
      <td>21:54</td><td>Register Audit</td><td>338.00</td><td>Employee</td>
      <td>Register #1: Over/Short: -1.70</td>
    </tr>
    <tr><td>19:33</td><td>Store Payout</td><td>30.00</td><td>Employee</td><td>gas</td></tr>
    <tr><td>18:30</td><td>Store Payout</td><td>21.25</td><td>Employee</td><td></td></tr>
    <tr><td>11:50</td><td>Payins</td><td>339.00</td><td>Employee</td><td>tips</td></tr>
    </tbody></table>
    <table class="table-standard"><thead><tr>
      <th></th><th>Sale Amount</th><th>Tip Amount</th><th>Deposit Amount</th>
    </tr></thead><tbody><tr><td>Total</td><td>1,841.60</td><td>133.35</td><td>1,974.95</td></tr></tbody></table>
    <table class="table-standard"><thead><tr>
      <th></th><th>Sale Amount</th><th>Tip Amount (Excluding WLD)</th><th>WLD Tip Amount</th><th>Deposit Amount</th>
    </tr></thead><tbody>
      <tr><td>Online Credit Card Total</td><td>1,048.75</td><td>42.10</td><td>10.50</td><td>1,101.35</td></tr>
      <tr><td>Online Gift Card Total</td><td>65.95</td><td>9.65</td><td>4.00</td><td>79.60</td></tr>
    </tbody></table>
    <table id="thirdpartyBreakdown"><thead><tr>
      <th>Payment Name</th><th>Ticket Count</th><th>Net Sales</th><th>Sales Tax</th><th>Total</th>
    </tr></thead><tbody><tr><td>DoorDash</td><td>25</td><td>516.16</td><td>21.05</td><td>537.21</td></tr></tbody></table>
    <table id="giftcardBreakdown"><tbody>
      <tr><td>Gift Cards Redeemed</td><td>21.40</td></tr>
      <tr><td>Gift Cards Sold</td><td>0.00</td></tr>
      <tr><td>Online Gift Card Tips</td><td>0.00</td></tr>
    </tbody></table>
    <table id="donationBreakdown"><thead><tr>
      <th>Donation Type</th><th>Quantity</th><th>Total</th>
    </tr></thead><tbody></tbody></table>
    <div>Total Credit Card Tips 175.45</div>
  `);
  const result = await scrapeCsdPage(page, "2006", "06/29/2026");
  assert.equal(result.sales["Non-Taxable Sales"], 3703.77);
  assert.equal(result.cards.saleAmount, 1841.60);
  assert.equal(result.registerAuditCid, 339.70);
  assert.equal(result.registerAudit, 338.00);
  assert.equal(result.cashOverShort, -0.70);
  assert.equal(result.registerAuditAdjustment, -1);
  assert.equal(result.payout, 51.25);
  assert.equal(result.payin, 339);
  assert.equal(result.onlineCreditCard.wldTipAmount, 10.50);
  assert.equal(result.thirdParty[0].netSales, 516.16);
  const rows = toComparisonRows(result);
  assert.deepEqual(rows.find(
    (row) => row["Transaction Category"] === "Register Audit"
  ), {
    Date: "06/29/2026", Class: "2006", "Transaction Category": "Register Audit",
    Debit: 338, Credit: ""
  });
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "In-Store Credit Card"
  ).Debit, 1974.95);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Payout"
  ).Debit, 51.25);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Payin"
  ).Credit, 339);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "3rd Party - DoorDash"
  ).Debit, 537.21);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Online Credit card"
  ).Debit, 1090.85);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Online Gift Card Tips"
  ).Credit, 9.65);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Online Gift Card"
  ).Debit, 75.60);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "In-Store Credit Card Tips"
  ).Credit, 123.70);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Cash Over/Short Adjustment"
  ).Debit, 0.70);
  assert.equal(rows.find(
    (row) => row["Transaction Category"] === "Register Audit Adjustment"
  ).Debit, 1);

  const cidOnly = {
    ...result,
    registerAuditCid: 216.24,
    registerAudit: 0,
    cashOverShort: 0,
    registerAuditAdjustment: 0
  };
  const cidOnlyRows = toComparisonRows(cidOnly);
  assert.equal(cidOnlyRows.find(
    (row) => row["Transaction Category"] === "Register Audit Adjustment"
  ).Debit, 216);
  assert.equal(cidOnlyRows.find(
    (row) => row["Transaction Category"] === "Cash Over/Short Adjustment"
  ).Debit, 0.24);
  await browser.close();
});
