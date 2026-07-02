"use strict";

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function amount(value) {
  const normalized = clean(value).replace(/[$,]/g, "").replace(/^\((.*)\)$/, "-$1");
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid monetary value: ${JSON.stringify(value)}`);
  }
  return parsed;
}

async function keyedTable(page, selector) {
  return page.locator(selector).evaluate((table) => {
    const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
    return [...table.querySelectorAll(":scope > tbody > tr")].map((row) => {
      const cells = [...row.children].map(text);
      return { key: cells[0] || "", values: cells.slice(1) };
    }).filter((row) => row.key);
  });
}

async function findTableByHeaders(page, headers) {
  const tables = page.locator("table.table-standard");
  for (let index = 0; index < await tables.count(); index += 1) {
    const table = tables.nth(index);
    const normalized = await table.evaluate((node) => {
      const text = (element) => (element?.textContent || "").replace(/\s+/g, " ").trim();
      return [...(node.tHead?.rows[0]?.cells || [])].map(text).filter(Boolean);
    });
    if (headers.every((header) => normalized.includes(header))) {
      return table;
    }
  }
  return null;
}

async function tableRecords(table) {
  if (!table) return [];
  return table.evaluate((node) => {
    const text = (element) => (element?.textContent || "").replace(/\s+/g, " ").trim();
    const headers = [...(node.tHead?.rows[0]?.cells || [])].map(text);
    const rows = node.tBodies[0]?.rows || [];
    return [...rows].map((row) => {
      const cells = [...row.cells].map(text);
      const record = {};
      for (let index = 0; index < headers.length; index += 1) {
        const header = headers[index];
        record[header || "Name"] = cells[index] || "";
      }
      return record;
    });
  });
}

async function optionalTableRecords(page, selector) {
  const table = page.locator(selector);
  return await table.count() ? tableRecords(table) : [];
}

function rowsToMap(rows) {
  return Object.fromEntries(rows.map((row) => [clean(row.key), row.values.map(clean)]));
}

async function scrapeCsdPage(page, expectedStore, expectedDate) {
  await page.locator("#salesBreakdown").waitFor({ state: "visible" });
  const store = await page.locator("#parameters\\:store").inputValue();
  const date = await page.locator("#parameters\\:startDateCalendarInputDate").inputValue();
  if (String(store).trim() !== String(expectedStore)) {
    throw new Error(`CSD store mismatch: expected ${expectedStore}, received ${store}`);
  }
  if (date !== expectedDate) {
    throw new Error(`CSD date mismatch: expected ${expectedDate}, received ${date}`);
  }

  const sales = rowsToMap(await keyedTable(page, "#salesBreakdown"));
  const giftCards = rowsToMap(await keyedTable(page, "#giftcardBreakdown"));
  const bank = await page.locator("#bankBreakdown").count()
    ? rowsToMap(await keyedTable(page, "#bankBreakdown"))
    : {};
  const thirdParty = await optionalTableRecords(page, "#thirdpartyBreakdown");
  const donations = await optionalTableRecords(page, "#donationBreakdown");
  const houseAccounts = await optionalTableRecords(page, "#houseBreakdown");
  const registerRows = await optionalTableRecords(page, "#registerAudit");
  const cardTable = await findTableByHeaders(page, ["Sale Amount", "Tip Amount", "Deposit Amount"]);
  const onlineTable = await findTableByHeaders(
    page,
    ["Sale Amount", "Tip Amount (Excluding WLD)", "WLD Tip Amount", "Deposit Amount"]
  );

  const cardRows = await tableRecords(cardTable);
  const onlineRows = await tableRecords(onlineTable);
  const cardTotal = cardRows.find((row) => clean(row.Name) === "Total") || {};
  const onlineCredit = onlineRows.find((row) => clean(row.Name) === "Online Credit Card Total") || {};
  const onlineGift = onlineRows.find((row) => clean(row.Name) === "Online Gift Card Total") || {};
  const totalTipsText = await page.locator("body").innerText();
  const totalTipsMatch = totalTipsText.match(/Total Credit Card Tips\s+([$,\d.-]+)/i);
  const totalCreditCardTips = amount(totalTipsMatch?.[1] || 0);

  let registerAudit = 0;
  let overShort = 0;
  for (const row of registerRows) {
    const rowAmount = amount(row.Amount || 0);
    const match = clean(row.Comment).match(/Over\/Short:\s*([-0-9.]+)/i);
    if (!match) continue;
    const rowOverShort = amount(match[1]);
    if (Math.abs(rowAmount - rowOverShort) < 0.0001) continue;
    registerAudit = rowAmount;
    overShort = rowOverShort;
    break;
  }
  const registerAuditAdjustment = Math.trunc(overShort);
  const cashOverShort = Math.round((overShort - registerAuditAdjustment) * 100) / 100;
  const payout = registerRows
    .filter((row) => clean(row.Type).toLowerCase() === "store payout")
    .reduce((sum, row) => sum + Math.abs(amount(row.Amount || 0)), 0);
  const payin = registerRows
    .filter((row) => clean(row.Type).toLowerCase() === "payins")
    .reduce((sum, row) => sum + amount(row.Amount || 0), 0);

  return {
    schemaVersion: 3,
    store: String(store).trim(),
    date,
    sales: Object.fromEntries(Object.entries(sales).map(([key, values]) => [key, amount(values[0])])),
    registerAuditCid: amount((bank["Register Audit(CID)"] || []).find((value) => clean(value)) || 0),
    registerAudit,
    cashOverShort,
    registerAuditAdjustment,
    payout,
    payin,
    cards: {
      saleAmount: amount(cardTotal["Sale Amount"] || 0),
      tipAmount: amount(cardTotal["Tip Amount"] || 0),
      depositAmount: amount(cardTotal["Deposit Amount"] || 0)
    },
    onlineCreditCard: {
      saleAmount: amount(onlineCredit["Sale Amount"] || 0),
      tipAmount: amount(onlineCredit["Tip Amount (Excluding WLD)"] || 0),
      wldTipAmount: amount(onlineCredit["WLD Tip Amount"] || 0),
      depositAmount: amount(onlineCredit["Deposit Amount"] || 0)
    },
    onlineGiftCard: {
      saleAmount: amount(onlineGift["Sale Amount"] || 0),
      tipAmount: amount(onlineGift["Tip Amount (Excluding WLD)"] || 0),
      wldTipAmount: amount(onlineGift["WLD Tip Amount"] || 0),
      depositAmount: amount(onlineGift["Deposit Amount"] || 0)
    },
    totalCreditCardTips,
    thirdParty: thirdParty.map((row) => ({
      paymentName: clean(row["Payment Name"]),
      ticketCount: Number(clean(row["Ticket Count"]).replace(/,/g, "")) || 0,
      netSales: amount(row["Net Sales"] || 0),
      salesTax: amount(row["Sales Tax"] || 0),
      total: amount(row.Total || 0)
    })).filter((row) => row.paymentName),
    giftCards: Object.fromEntries(
      Object.entries(giftCards).map(([key, values]) => [key, amount(values[0])])
    ),
    houseAccounts: houseAccounts.map((row) => ({
      name: clean(row.Name),
      amount: amount(row.Amount || 0)
    })).filter((row) => row.name),
    donations: donations.map((row) => ({
      donationType: clean(row["Donation Type"]),
      quantity: Number(clean(row.Quantity).replace(/,/g, "")) || 0,
      total: amount(row.Total || 0)
    })).filter((row) => row.donationType)
  };
}

function category(date, store, name, debit, credit) {
  return { Date: date, Class: store, "Transaction Category": name, Debit: debit, Credit: credit };
}

function toComparisonRows(result) {
  const rows = [];
  const add = (name, debit = 0, credit = 0) => {
    debit = Math.round((Number(debit) || 0) * 100) / 100;
    credit = Math.round((Number(credit) || 0) * 100) / 100;
    if (Math.abs(debit) < 0.001 && Math.abs(credit) < 0.001) return;
    rows.push(category(result.date, result.store, name, debit || "", credit || ""));
  };
  add("Subject to Tax", 0, result.sales["Taxable Sales"]);
  const nonTax = result.sales["Non-Taxable Sales"] || 0;
  add("Non-Taxable Sales", nonTax < 0 ? Math.abs(nonTax) : 0, nonTax > 0 ? nonTax : 0);
  add("3rd Party Tax Exempt", 0, result.sales["3rd Party Tax Exempt Sales"]);
  add("Tax Exempt", 0, result.sales["Tax Exempt Sales"]);
  add("Register Audit", result.registerAudit);
  add("Sales Tax", 0, result.sales["Sales Tax"]);
  add("In-Store Credit Card", result.cards.depositAmount);
  add("Payout", result.payout);
  add("Online Credit card", result.onlineCreditCard.saleAmount + result.onlineCreditCard.tipAmount);
  add(
    "Online Gift Card",
    result.onlineGiftCard.saleAmount + result.onlineGiftCard.tipAmount
  );
  add("Online Credit Card Tips", 0, result.onlineCreditCard.tipAmount);
  add(
    "In-Store Credit Card Tips",
    0,
    (result.totalCreditCardTips || 0)
      - result.onlineCreditCard.tipAmount
      - result.onlineGiftCard.tipAmount
  );
  add(
    "Online Gift Card Tips",
    0,
    result.onlineGiftCard.tipAmount
  );
  add("Gift Card", result.giftCards["Gift Cards Redeemed"]);
  add("Gift Card Sold", 0, result.giftCards["Gift Cards Sold"]);

  const thirdPartyNames = {
    DoorDash: "3rd Party - DoorDash",
    GrubHub: "3rd Party - GrubHub",
    UberEats: "3rd Party - UberEats",
    "EZ Cater": "3rd Party - EZ Cater"
  };
  for (const item of (result.thirdParty || [])) {
    add(thirdPartyNames[item.paymentName] || `3rd Party - ${item.paymentName}`, item.total);
  }
  add("House Account", (result.houseAccounts || []).reduce((sum, item) => sum + item.amount, 0));
  add("Donation", 0, (result.donations || []).reduce((sum, item) => sum + item.total, 0));
  add("Payin", 0, result.payin);
  let cos = result.cashOverShort || 0;
  let adjustment = result.registerAuditAdjustment || 0;
  if (
    !(result.registerAudit || 0)
    && !cos
    && !adjustment
    && (result.registerAuditCid || 0)
  ) {
    const cid = result.registerAuditCid;
    const whole = Math.trunc(cid);
    adjustment = -whole;
    cos = -Math.round((cid - whole) * 100) / 100;
  }
  add("Cash Over/Short Adjustment", cos < 0 ? Math.abs(cos) : 0, cos > 0 ? cos : 0);
  add(
    "Register Audit Adjustment",
    adjustment < 0 ? Math.abs(adjustment) : 0,
    adjustment > 0 ? adjustment : 0
  );
  return rows;
}

module.exports = { amount, scrapeCsdPage, toComparisonRows };
