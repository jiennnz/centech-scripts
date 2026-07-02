#!/usr/bin/env node
"use strict";

const fs = require("fs/promises");
const path = require("path");
const { toComparisonRows } = require("./csd");

function csvValue(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

async function run() {
  const runDir = path.resolve(process.argv[2] || "");
  if (!process.argv[2]) throw new Error("Usage: node rebuild.js <financial-run-directory>");
  const aggregatePath = path.join(runDir, "csd_aggregates.jsonl");
  const outputPath = path.join(runDir, "scraped_data_flexe.csv");
  const resultMap = new Map();
  for (const result of (await fs.readFile(aggregatePath, "utf8"))
    .split(/\r?\n/).filter(Boolean).map(JSON.parse)) {
    resultMap.set(`${result.store}|${result.date}`, result);
  }
  const results = [...resultMap.values()];
  const rows = results.flatMap(toComparisonRows);
  const columns = ["Date", "Class", "Transaction Category", "Debit", "Credit"];
  const output = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvValue(row[column])).join(","))
  ].join("\n") + "\n";
  await fs.writeFile(outputPath, output, "utf8");
  console.log(`Wrote ${rows.length} rows to ${outputPath}`);
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
