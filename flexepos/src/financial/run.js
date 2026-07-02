#!/usr/bin/env node
"use strict";

const fs = require("fs/promises");
const path = require("path");
const YAML = require("yaml");
const { openAuthenticatedContext } = require("../browser");
const { scrapeCsdPage, toComparisonRows } = require("./csd");

function parseArgs(argv) {
  const args = { org: "century", delayMs: 1500, mode: "headed" };
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

function datesBetween(start, end) {
  const first = parseIsoDate(start);
  const last = parseIsoDate(end);
  if (first > last) throw new Error("--start must be on or before --end.");
  const dates = [];
  for (let current = first; current <= last; current = new Date(current.valueOf() + 86400000)) {
    dates.push(current.toISOString().slice(0, 10));
  }
  return dates;
}

function flexDate(iso) {
  const [year, month, day] = iso.split("-");
  return `${month}/${day}/${year}`;
}

async function loadStores(repoRoot, org) {
  const rulePath = path.join(repoRoot, "financial", "sales_export_comparison", "rules", `${org}.yaml`);
  const rule = YAML.parse(await fs.readFile(rulePath, "utf8"));
  const stores = (rule.stores || []).map(String).map((value) => value.trim()).filter(Boolean);
  if (!stores.length) throw new Error(`No stores configured in ${rulePath}`);
  return stores;
}

function csvValue(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function csv(rows, columns) {
  return [
    columns.map(csvValue).join(","),
    ...rows.map((row) => columns.map((column) => csvValue(row[column])).join(","))
  ].join("\n") + "\n";
}

async function readCompleted(jsonlPath) {
  try {
    const lines = (await fs.readFile(jsonlPath, "utf8")).split(/\r?\n/).filter(Boolean);
    return new Set(lines.map((line) => {
      const item = JSON.parse(line);
      return item.schemaVersion === 3 ? `${item.store}|${item.date}` : null;
    }).filter(Boolean));
  } catch (error) {
    if (error.code === "ENOENT") return new Set();
    throw error;
  }
}

async function locateCsd(page) {
  await page.goto("https://fms.flexepos.com/FlexeposWeb/home.seam", {
    waitUntil: "domcontentloaded"
  });
  const corporateReports = page.locator(".menu-header", {
    hasText: "Corporate Reports"
  }).first();
  await corporateReports.waitFor({ state: "visible" });
  await corporateReports.click();

  const link = page.getByRole("link", { name: "CSD Daily Sales", exact: true });
  await link.waitFor({ state: "visible" });
  return link.getAttribute("href");
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const stores = args.stores
    ? args.stores.split(",").map((value) => value.trim()).filter(Boolean)
    : await loadStores(repoRoot, args.org);
  const dates = datesBetween(args.start, args.end);
  const runDir = path.resolve(
    args.outputDir || path.join(repoRoot, "flexepos", "runs", `${args.start}_${args.end}`, args.org, "financial")
  );
  const aggregatePath = path.join(runDir, "csd_aggregates.jsonl");
  const comparisonPath = path.join(runDir, "scraped_data_flexe.csv");
  const manifestPath = path.join(runDir, "export_manifest.csv");
  await fs.mkdir(runDir, { recursive: true });

  const completed = await readCompleted(aggregatePath);
  const manifest = [];
  const { browser, page } = await openAuthenticatedContext({
    statePath: path.join(repoRoot, "flexepos", ".auth", "storage-state.json"),
    headless: args.mode === "headless"
  });

  try {
    const csdHref = await locateCsd(page);
    const csdUrl = new URL(csdHref, page.url()).href;
    for (const isoDate of dates) {
      for (const store of stores) {
        const expectedDate = flexDate(isoDate);
        const key = `${store}|${expectedDate}`;
        if (completed.has(key)) {
          manifest.push({ Date: expectedDate, Store: store, Status: "skipped", Error: "" });
          continue;
        }

        try {
          await page.goto(csdUrl, { waitUntil: "domcontentloaded" });
          await page.locator("#parameters\\:store").fill(store);
          await page.locator("#parameters\\:startDateCalendarInputDate").fill(expectedDate);
          await Promise.all([
            page.waitForLoadState("domcontentloaded").catch(() => {}),
            page.locator("#parameters\\:submit").click()
          ]);
          const result = await scrapeCsdPage(page, store, expectedDate);
          await fs.appendFile(aggregatePath, `${JSON.stringify(result)}\n`, "utf8");
          completed.add(key);
          manifest.push({ Date: expectedDate, Store: store, Status: "success", Error: "" });
          console.log(`[success] ${expectedDate} store ${store}`);
        } catch (error) {
          manifest.push({ Date: expectedDate, Store: store, Status: "failed", Error: error.message });
          console.error(`[failed] ${expectedDate} store ${store}: ${error.message}`);
        }
        await page.waitForTimeout(Number(args.delayMs));
      }
    }
  } finally {
    await browser.close();
  }

  const resultMap = new Map();
  for (const result of (await fs.readFile(aggregatePath, "utf8"))
    .split(/\r?\n/).filter(Boolean).map(JSON.parse)) {
    resultMap.set(`${result.store}|${result.date}`, result);
  }
  const results = [...resultMap.values()];
  const comparisonRows = results.flatMap(toComparisonRows);
  await fs.writeFile(
    comparisonPath,
    csv(comparisonRows, ["Date", "Class", "Transaction Category", "Debit", "Credit"]),
    "utf8"
  );
  await fs.writeFile(manifestPath, csv(manifest, ["Date", "Store", "Status", "Error"]), "utf8");
  console.log(`Comparison CSV: ${comparisonPath}`);
  console.log(`Manifest CSV  : ${manifestPath}`);
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
