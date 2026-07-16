#!/usr/bin/env node
"use strict";

const fs = require("fs/promises");
const path = require("path");
const { toComparisonRows } = require("./csd");

function localIsoDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseArgs(argv) {
  const args = { org: "century", runDate: localIsoDate() };
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
  for (const [name, value] of [["--start", args.start], ["--end", args.end], ["--run-date", args.runDate]]) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${name} must use YYYY-MM-DD.`);
  }
  if (args.start > args.end) throw new Error("--start must be on or before --end.");
  return args;
}

function isoFromFlexDate(value) {
  const [month, day, year] = value.split("/");
  return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
}

function csvValue(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(rows, columns) {
  return [
    columns.map(csvValue).join(","),
    ...rows.map((row) => columns.map((column) => csvValue(row[column])).join(","))
  ].join("\n") + "\n";
}

async function exists(filePath) {
  return fs.access(filePath).then(() => true).catch(() => false);
}

async function findAggregateFiles(rootDir, org) {
  const files = [];

  async function walk(dir) {
    let entries = [];
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch (error) {
      if (error.code === "ENOENT") return;
      throw error;
    }

    for (const entry of entries) {
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(entryPath);
      } else if (
        entry.name === "csd_aggregates.jsonl" &&
        entryPath.includes(`${path.sep}${org}${path.sep}financial${path.sep}`)
      ) {
        files.push(entryPath);
      }
    }
  }

  await walk(rootDir);
  return files.sort();
}

async function readJsonl(filePath) {
  const raw = await fs.readFile(filePath, "utf8");
  return raw.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

async function mergeManifests(aggregateFiles, start, end) {
  const rows = [];
  for (const aggregatePath of aggregateFiles) {
    const manifestPath = path.join(path.dirname(aggregatePath), "export_manifest.csv");
    if (!(await exists(manifestPath))) continue;
    const raw = await fs.readFile(manifestPath, "utf8");
    const lines = raw.split(/\r?\n/).filter(Boolean);
    if (lines.length < 2) continue;
    const header = lines[0].split(",");
    const dateIndex = header.indexOf("Date");
    const storeIndex = header.indexOf("Store");
    const statusIndex = header.indexOf("Status");
    const errorIndex = header.indexOf("Error");
    if (dateIndex < 0 || storeIndex < 0 || statusIndex < 0) continue;
    for (const line of lines.slice(1)) {
      const columns = line.split(",");
      const isoDate = isoFromFlexDate(columns[dateIndex]);
      if (isoDate < start || isoDate > end) continue;
      rows.push({
        Date: columns[dateIndex],
        Store: columns[storeIndex],
        Status: columns[statusIndex],
        Error: errorIndex >= 0 ? columns[errorIndex] || "" : "",
        Source: path.relative(process.cwd(), path.dirname(aggregatePath))
      });
    }
  }
  return rows;
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const batchRoot = path.resolve(
    repoRoot,
    args.batchRoot || path.join("flexepos", "runs", args.runDate, "financial_batches")
  );
  const outputDir = path.resolve(
    repoRoot,
    args.outputDir || path.join("flexepos", "runs", args.runDate, `${args.start}_${args.end}`, args.org, "financial")
  );

  const aggregateFiles = await findAggregateFiles(batchRoot, args.org);
  if (!aggregateFiles.length) {
    throw new Error(`No batch aggregate files found under ${batchRoot}`);
  }

  const merged = new Map();
  for (const filePath of aggregateFiles) {
    for (const item of await readJsonl(filePath)) {
      if (item.schemaVersion !== 3) continue;
      const isoDate = isoFromFlexDate(item.date);
      if (isoDate < args.start || isoDate > args.end) continue;
      merged.set(`${item.store}|${item.date}`, item);
    }
  }

  const results = [...merged.values()].sort((left, right) => {
    const leftDate = isoFromFlexDate(left.date);
    const rightDate = isoFromFlexDate(right.date);
    return leftDate.localeCompare(rightDate) || String(left.store).localeCompare(String(right.store), undefined, { numeric: true });
  });
  if (!results.length) {
    throw new Error(`No aggregate rows found for ${args.start} -> ${args.end} under ${batchRoot}`);
  }

  await fs.mkdir(outputDir, { recursive: true });
  const aggregatePath = path.join(outputDir, "csd_aggregates.jsonl");
  const comparisonPath = path.join(outputDir, "scraped_data_flexe.csv");
  const manifestPath = path.join(outputDir, "export_manifest.csv");

  await fs.writeFile(aggregatePath, results.map((item) => JSON.stringify(item)).join("\n") + "\n", "utf8");
  await fs.writeFile(
    comparisonPath,
    toCsv(results.flatMap(toComparisonRows), ["Date", "Class", "Transaction Category", "Debit", "Credit"]),
    "utf8"
  );
  await fs.writeFile(
    manifestPath,
    toCsv(await mergeManifests(aggregateFiles, args.start, args.end), ["Date", "Store", "Status", "Error", "Source"]),
    "utf8"
  );

  console.log(`Batch root    : ${batchRoot}`);
  console.log(`Output dir    : ${outputDir}`);
  console.log(`Aggregate rows: ${results.length}`);
  console.log(`Comparison CSV: ${comparisonPath}`);
  console.log(`Manifest CSV  : ${manifestPath}`);
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
