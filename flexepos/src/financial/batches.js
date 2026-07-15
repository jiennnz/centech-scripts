#!/usr/bin/env node
"use strict";

const path = require("path");
const { spawn } = require("child_process");

function parseArgs(argv) {
  const args = { org: "century", mode: "headed", sessions: "1" };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) throw new Error(`Unexpected argument: ${key}`);
    const name = key.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${key}`);
    args[name] = value;
    index += 1;
  }
  if (!args.ranges) {
    throw new Error("--ranges is required, for example 2026-06-29:2026-07-03,2026-07-04:2026-07-08");
  }
  if (!["headed", "headless"].includes(args.mode)) {
    throw new Error("--mode must be either headed or headless.");
  }
  return args;
}

function parseRanges(value) {
  return value.split(",").map((range) => {
    const [start, end] = range.split(":").map((part) => part && part.trim());
    if (!start || !end) throw new Error(`Invalid range: ${range}`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) {
      throw new Error(`Ranges must use YYYY-MM-DD: ${range}`);
    }
    return { start, end };
  });
}

function passThroughArgs(args) {
  const passthrough = [];
  for (const name of [
    "stores",
    "delayMs",
    "timeoutMs",
    "navigationTimeoutMs",
    "loginTimeoutMs"
  ]) {
    if (args[name]) {
      passthrough.push(`--${name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`, args[name]);
    }
  }
  return passthrough;
}

function runBatch(batch, sessionNumber, args, extraArgs) {
  const authState = `flexepos/.auth/session-${sessionNumber}.json`;
  const outputDir = `flexepos/runs/${batch.start}_${batch.end}/${args.org}/financial`;
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const runnerPath = path.join(repoRoot, "flexepos", "src", "financial", "run.js");
  const childArgs = [
    runnerPath,
    "--start",
    batch.start,
    "--end",
    batch.end,
    "--org",
    args.org,
    "--mode",
    args.mode,
    "--auth-state",
    authState,
    "--output-dir",
    outputDir,
    ...extraArgs
  ];

  console.log(`[batch ${sessionNumber}] ${batch.start} -> ${batch.end} using ${authState}`);
  const child = spawn(process.execPath, childArgs, {
    cwd: repoRoot,
    stdio: "inherit",
    shell: false
  });

  return new Promise((resolve) => {
    child.on("exit", (code) => resolve({ code, batch, sessionNumber }));
  });
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const ranges = parseRanges(args.ranges);
  const sessions = Number(args.sessions);
  if (!Number.isInteger(sessions) || sessions < 1) throw new Error("--sessions must be a positive integer.");
  if (ranges.length > sessions) {
    throw new Error(`Got ${ranges.length} ranges but only ${sessions} sessions. Add sessions or reduce ranges.`);
  }

  const extraArgs = passThroughArgs(args);
  const results = await Promise.all(
    ranges.map((batch, index) => runBatch(batch, index + 1, args, extraArgs))
  );
  const failed = results.filter((result) => result.code !== 0);
  if (failed.length) {
    for (const result of failed) {
      console.error(
        `[failed] session-${result.sessionNumber}: ${result.batch.start} -> ${result.batch.end} exited ${result.code}`
      );
    }
    process.exitCode = 1;
  }
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
