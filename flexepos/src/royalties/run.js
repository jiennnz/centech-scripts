#!/usr/bin/env node
"use strict";

const fs = require("fs/promises");
const path = require("path");
const YAML = require("yaml");
const { openAuthenticatedContext } = require("../browser");

const REQUIRED_COLUMNS = [
  "DateRange",
  "Class",
  "Transaction Category",
  "Account Number",
  "Account Name",
  "Debit",
  "Credit"
];

const EXPORT_COLUMNS = [
  "DateRange",
  "Class",
  "NetSales",
  "Transaction Category",
  "Account Number",
  "Account Name",
  "Debit",
  "Credit",
  "Memo",
  "IsBalanced",
  "Export Status"
];

const REPORT_NAMES = [
  "Royalty Report",
  "ERP Royality Review Report",
  "ERP Royalty Review Report",
  "Royality Review Report",
  "Royalty Review Report"
];

const DEFAULT_ROYALTY_REPORT_URL =
  "https://fms.flexepos.com/FlexeposWeb/royalty.seam?cid=268311";

const ROYALTY_CATEGORY_MAP = [
  {
    category: "Royalty Fee",
    amountKey: "royalty",
    debit: true,
    accountNumber: "651000",
    accountName: "Royalties"
  },
  {
    category: "Royalties Bank Acct Entry",
    amountKey: "royalty",
    debit: false,
    accountNumber: "217000",
    accountName: "Accrued Royalties"
  },
  {
    category: "National Media Fee",
    amountKey: "media",
    debit: true,
    accountNumber: "560000",
    accountName: "Advertising-National"
  },
  {
    category: "National Media Bank Entry",
    amountKey: "media",
    debit: false,
    accountNumber: "217000",
    accountName: "Accrued Royalties"
  },
  {
    category: "Corporate Advertising Fee",
    amountKey: "advertising",
    debit: true,
    accountNumber: "560001",
    accountName: "Advertising-Production Fund"
  },
  {
    category: "Corp Advertising Bank Acct Entry",
    amountKey: "advertising",
    debit: false,
    accountNumber: "217000",
    accountName: "Accrued Royalties"
  }
];

function parseArgs(argv) {
  const args = { org: "century", mode: "headed", reportName: REPORT_NAMES[0] };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) throw new Error(`Unexpected argument: ${key}`);
    const name = key.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${key}`);
    args[name] = value;
    index += 1;
  }
  if (!args.start || !args.end) throw new Error("--start and --end are required (YYYY-MM-DD).");
  if (!["headed", "headless"].includes(args.mode)) {
    throw new Error("--mode must be either headed or headless.");
  }
  parseIsoDate(args.start);
  parseIsoDate(args.end);
  return args;
}

function parseIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`Invalid ISO date: ${value}`);
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error(`Invalid calendar date: ${value}`);
  }
  return parsed;
}

function flexDate(iso) {
  const [year, month, day] = iso.split("-");
  return `${month}/${day}/${year}`;
}

function clean(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function csvValue(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(rows, columns) {
  return [
    columns.map(csvValue).join(","),
    ...rows.map((row) => columns.map((column) => csvValue(row[column] ?? "")).join(","))
  ].join("\n") + "\n";
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quoted) {
      if (char === '"' && next === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  if (!rows.length) return [];
  const headers = rows[0].map(clean);
  return rows.slice(1).filter((cells) => cells.some((cell) => clean(cell))).map((cells) => {
    const record = {};
    for (let index = 0; index < headers.length; index += 1) {
      record[headers[index]] = cells[index] ?? "";
    }
    return record;
  });
}

async function loadStores(repoRoot, org) {
  const rulePath = path.join(repoRoot, "financial", "sales_export_comparison", "rules", `${org}.yaml`);
  const rule = YAML.parse(await fs.readFile(rulePath, "utf8"));
  const stores = new Set((rule.stores || []).map(String).map((value) => value.trim()).filter(Boolean));
  if (!stores.size) throw new Error(`No stores configured in ${rulePath}`);
  return stores;
}

function normalizeStore(value) {
  const text = clean(value);
  return /^\d+\.0$/.test(text) ? text.slice(0, -2) : text.split(/[ -]/)[0];
}

function parseDateText(value) {
  const text = clean(value);
  const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return new Date(`${iso[1]}-${iso[2]}-${iso[3]}T00:00:00Z`);
  const us = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (us) {
    const month = us[1].padStart(2, "0");
    const day = us[2].padStart(2, "0");
    return new Date(`${us[3]}-${month}-${day}T00:00:00Z`);
  }
  return null;
}

function dateRangeOverlaps(value, start, end) {
  const parts = clean(value).split(/\s+-\s+/);
  const first = parseDateText(parts[0]);
  const last = parseDateText(parts[1] || parts[0]);
  if (!first || !last) return false;
  const targetStart = parseIsoDate(start);
  const targetEnd = parseIsoDate(end);
  return first <= targetEnd && last >= targetStart;
}

function parseMoney(value) {
  const text = clean(value).replace(/[$,]/g, "").replace(/^\((.*)\)$/, "-$1");
  if (!text) return "0.00";
  const parsed = Number(text);
  if (!Number.isFinite(parsed)) return clean(value);
  return parsed.toFixed(2);
}

function amount(value) {
  const parsed = Number(parseMoney(value));
  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid monetary value: ${JSON.stringify(value)}`);
  }
  return parsed;
}

function selectedStores(configuredStores, args) {
  if (!args.stores) return [...configuredStores];
  const requested = args.stores.split(",").map((value) => value.trim()).filter(Boolean);
  const missing = requested.filter((store) => !configuredStores.has(store));
  if (missing.length) {
    throw new Error(`Requested stores are not configured for ${args.org}: ${missing.join(", ")}`);
  }
  return requested;
}

function normalizeRows(rows, stores, start, end) {
  if (!rows.length) throw new Error("Royalty export is empty.");
  const observedColumns = new Set(Object.keys(rows[0]).map(clean));
  const missing = REQUIRED_COLUMNS.filter((column) => !observedColumns.has(column));
  if (missing.length) {
    throw new Error(`Royalty export missing required columns: ${missing.join(", ")}`);
  }

  return rows.map((row) => {
    const out = {};
    for (const column of EXPORT_COLUMNS) out[column] = row[column] ?? "";
    out.Class = normalizeStore(out.Class);
    out.Debit = parseMoney(out.Debit);
    out.Credit = parseMoney(out.Credit);
    return out;
  }).filter((row) => (
    stores.has(String(row.Class))
    && dateRangeOverlaps(row.DateRange, start, end)
  ));
}

async function normalizeCsvFile(sourcePath, outputPath, stores, start, end) {
  const raw = await fs.readFile(sourcePath, "utf8");
  const rows = normalizeRows(parseCsv(raw.replace(/^\uFEFF/, "")), stores, start, end);
  if (!rows.length) throw new Error("No royalty rows matched configured organization stores.");
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, toCsv(rows, EXPORT_COLUMNS), "utf8");
  return rows.length;
}

async function locateReport(page, args) {
  if (args.reportUrl) return args.reportUrl;
  if (args.reportCid) {
    return `https://fms.flexepos.com/FlexeposWeb/royalty.seam?cid=${args.reportCid}`;
  }

  try {
    await page.goto("https://fms.flexepos.com/FlexeposWeb/home.seam", {
      waitUntil: "domcontentloaded"
    });
    const corporateReports = page.locator(".menu-header", { hasText: "Corporate Reports" }).first();
    await corporateReports.waitFor({ state: "visible", timeout: 10000 });
    await corporateReports.click();

    const names = [args.reportName, ...REPORT_NAMES].filter(Boolean);
    for (const name of [...new Set(names)]) {
      const link = page.getByRole("link", { name, exact: true });
      if (await link.count()) {
        await link.first().waitFor({ state: "visible", timeout: 5000 });
        const href = await link.first().getAttribute("href");
        if (href) return new URL(href, page.url()).href;
      }
    }
  } catch (error) {
    console.warn(`[navigation] Royalty menu unavailable; using direct report URL: ${error.message}`);
  }
  console.warn(`[navigation] Royalty Report link not found; using direct report URL: ${DEFAULT_ROYALTY_REPORT_URL}`);
  return DEFAULT_ROYALTY_REPORT_URL;
}

async function fillFirstVisible(page, selectors, value) {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (!(await locator.count())) continue;
    try {
      await locator.waitFor({ state: "visible", timeout: 2000 });
      await locator.fill(value);
      return true;
    } catch {
      // Try the next candidate.
    }
  }
  return false;
}

async function fillDateParameters(page, start, end) {
  const startText = flexDate(start);
  const endText = flexDate(end);
  const startOk = await fillFirstVisible(page, [
    "#parameters\\:startDateCalendarInputDate",
    "#parameters\\:startDateInputDate",
    "input[name*='startDate']",
    "input[id*='startDate']"
  ], startText);
  const endOk = await fillFirstVisible(page, [
    "#parameters\\:endDateCalendarInputDate",
    "#parameters\\:endDateInputDate",
    "input[name*='endDate']",
    "input[id*='endDate']"
  ], endText);
  if (!startOk || !endOk) {
    throw new Error("Could not find visible start/end date fields on the royalty report page.");
  }
}

async function fillStoreParameter(page, store) {
  const ok = await fillFirstVisible(page, [
    "#parameters\\:store",
    "input[name*='store']",
    "input[id*='store']"
  ], store);
  if (!ok) {
    throw new Error("Could not find visible store field on the royalty report page.");
  }
}

async function submitReport(page) {
  const submit = page.getByRole("button", { name: /^submit$/i }).first();
  await submit.waitFor({ state: "visible", timeout: 10000 });
  await Promise.all([
    page.waitForLoadState("networkidle").catch(() => {}),
    submit.click()
  ]);
}

async function scrapeRoyaltyPage(page, expectedStore, start, end) {
  const expectedRange = `${flexDate(start)} - ${flexDate(end)}`;
  await page.getByText(/Royalty Sales/i).first().waitFor({ state: "visible", timeout: 30000 });
  const bodyText = await page.locator("body").innerText();
  if (!bodyText.includes(`Store: ${expectedStore}`) && !bodyText.includes(`Store ${expectedStore}`)) {
    throw new Error(`Royalty store mismatch: expected ${expectedStore}.`);
  }
  if (!bodyText.includes(expectedRange)) {
    throw new Error(`Royalty date range mismatch: expected ${expectedRange}.`);
  }

  const row = await page.locator("table").evaluateAll((tables, store) => {
    const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
    for (const table of tables) {
      const headerRows = [...table.querySelectorAll("thead tr, tr")];
      const header = headerRows.map((tr) => [...tr.cells].map(text))
        .find((cells) => (
          cells.includes("Store")
          && cells.includes("Royalty Sales")
          && cells.includes("Royalty")
          && cells.includes("Advertising")
          && cells.includes("Media")
        ));
      if (!header) continue;
      const rows = [...(table.tBodies[0]?.rows || table.rows)];
      for (const tr of rows) {
        const cells = [...tr.cells].map(text);
        if (cells[0] === String(store)) return cells;
      }
    }
    return null;
  }, expectedStore);

  if (!row) {
    throw new Error(`No royalty result row found for store ${expectedStore}.`);
  }
  if (row.length < 10) {
    throw new Error(`Royalty result row for store ${expectedStore} has ${row.length} columns; expected at least 10.`);
  }

  return {
    schemaVersion: 1,
    store: String(expectedStore),
    startDate: start,
    endDate: end,
    dateRange: expectedRange,
    royaltySales: amount(row[1]),
    royalty: amount(row[2]),
    royaltyPct: Number(clean(row[3])) || 0,
    advertising: amount(row[4]),
    advertisingPct: Number(clean(row[5])) || 0,
    media: amount(row[6]),
    mediaPct: Number(clean(row[7])) || 0,
    days: clean(row[8]),
    stateId: clean(row[9])
  };
}

function toRoyaltyExportRows(result) {
  return ROYALTY_CATEGORY_MAP.map((item) => {
    const value = Number(result[item.amountKey] || 0).toFixed(2);
    return {
      DateRange: result.dateRange,
      Class: result.store,
      NetSales: Number(result.royaltySales || 0).toFixed(2),
      "Transaction Category": item.category,
      "Account Number": item.accountNumber,
      "Account Name": item.accountName,
      Debit: item.debit ? value : "0.00",
      Credit: item.debit ? "0.00" : value,
      Memo: `TQSR - ${item.category}`,
      IsBalanced: "0",
      "Export Status": ""
    };
  });
}

async function readCompleted(aggregatePath) {
  try {
    const lines = (await fs.readFile(aggregatePath, "utf8")).split(/\r?\n/).filter(Boolean);
    return new Set(lines.map((line) => {
      const item = JSON.parse(line);
      return item.schemaVersion === 1 ? `${item.store}|${item.startDate}|${item.endDate}` : null;
    }).filter(Boolean));
  } catch (error) {
    if (error.code === "ENOENT") return new Set();
    throw error;
  }
}

async function writeRoyaltyExport(aggregatePath, outputPath) {
  let raw = "";
  try {
    raw = await fs.readFile(aggregatePath, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") return 0;
    throw error;
  }
  const lines = raw.split(/\r?\n/).filter(Boolean);
  const resultMap = new Map();
  for (const line of lines) {
    const result = JSON.parse(line);
    resultMap.set(`${result.store}|${result.startDate}|${result.endDate}`, result);
  }
  const rows = [...resultMap.values()].flatMap(toRoyaltyExportRows);
  await fs.writeFile(outputPath, toCsv(rows, EXPORT_COLUMNS), "utf8");
  return rows.length;
}

async function scrapeRoyaltyReport(args, runDir, stores) {
  const aggregatePath = path.join(runDir, "royalty_aggregates.jsonl");
  const outputPath = path.join(runDir, "client_royalties.csv");
  const manifestPath = path.join(runDir, "export_manifest.csv");
  const debugDir = path.join(runDir, "debug");
  await fs.mkdir(runDir, { recursive: true });
  await fs.mkdir(debugDir, { recursive: true });
  const completed = await readCompleted(aggregatePath);
  const manifest = [];

  const { browser, page } = await openAuthenticatedContext({
    statePath: args.authState
      ? path.resolve(args.repoRoot, args.authState)
      : path.join(args.repoRoot, "flexepos", ".auth", "storage-state.json"),
    headless: args.mode === "headless",
    timeoutMs: args.timeoutMs,
    navigationTimeoutMs: args.navigationTimeoutMs,
    loginTimeoutMs: args.loginTimeoutMs
  });
  try {
    const reportUrl = await locateReport(page, args);
    for (const store of stores) {
      const key = `${store}|${args.start}|${args.end}`;
      if (completed.has(key)) {
        manifest.push({ Store: store, Start: args.start, End: args.end, Status: "skipped", Error: "" });
        continue;
      }
      try {
        await page.goto(reportUrl, { waitUntil: "domcontentloaded" });
        await fillStoreParameter(page, store);
        await fillDateParameters(page, args.start, args.end);
        await submitReport(page);
        const result = await scrapeRoyaltyPage(page, store, args.start, args.end);
        await fs.appendFile(aggregatePath, `${JSON.stringify(result)}\n`, "utf8");
        completed.add(key);
        manifest.push({ Store: store, Start: args.start, End: args.end, Status: "success", Error: "" });
        console.log(`[success] ${args.start} -> ${args.end} store ${store}`);
      } catch (error) {
        const debugBase = `${store}_${args.start}_${args.end}`.replace(/[^0-9A-Za-z_-]/g, "_");
        try {
          await page.screenshot({ path: path.join(debugDir, `${debugBase}.png`), fullPage: true });
          await fs.writeFile(path.join(debugDir, `${debugBase}.html`), await page.content(), "utf8");
        } catch {
          // Best-effort debug artifacts only.
        }
        manifest.push({ Store: store, Start: args.start, End: args.end, Status: "failed", Error: error.message });
        console.error(`[failed] ${args.start} -> ${args.end} store ${store}: ${error.message}`);
      }
    }
  } finally {
    await browser.close();
  }

  const rows = await writeRoyaltyExport(aggregatePath, outputPath);
  await fs.writeFile(manifestPath, toCsv(manifest, ["Store", "Start", "End", "Status", "Error"]), "utf8");
  if (rows === 0 && manifest.some((row) => row.Status === "failed")) {
    throw new Error(`No royalty rows were scraped. Manifest CSV: ${manifestPath}`);
  }
  return { outputPath, manifestPath, rows };
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  args.repoRoot = repoRoot;
  const configuredStores = await loadStores(repoRoot, args.org);
  const stores = selectedStores(configuredStores, args);
  const storeSet = new Set(stores);
  const runDir = path.resolve(
    args.outputDir || path.join(repoRoot, "flexepos", "runs", `${args.start}_${args.end}`, args.org, "royalties")
  );
  const outputPath = path.join(runDir, "client_royalties.csv");
  const manifestPath = path.join(runDir, "export_manifest.csv");

  if (args.sourceCsv) {
    const sourcePath = path.resolve(repoRoot, args.sourceCsv);
    const rows = await normalizeCsvFile(sourcePath, outputPath, storeSet, args.start, args.end);
    await fs.writeFile(
      manifestPath,
      toCsv([{
        Start: args.start,
        End: args.end,
        Org: args.org,
        Source: sourcePath,
        Output: outputPath,
        Rows: rows
      }], ["Start", "End", "Org", "Source", "Output", "Rows"]),
      "utf8"
    );
    console.log(`Royalty CSV   : ${outputPath}`);
    console.log(`Manifest CSV  : ${manifestPath}`);
    return;
  }

  const result = await scrapeRoyaltyReport(args, runDir, stores);
  console.log(`Royalty CSV   : ${result.outputPath}`);
  console.log(`Manifest CSV  : ${result.manifestPath}`);
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
