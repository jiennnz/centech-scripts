#!/usr/bin/env node
"use strict";

const fs = require("fs/promises");
const path = require("path");
const { openAuthenticatedContext } = require("../browser");

const DEFAULT_REPORT_URL = "https://fms.flexepos.com/FlexeposWeb/tools/payroll.seam?cid=232198";
const COLUMNS = [
  "Store", "Start Date", "End Date", "Employee Name", "Employee Number",
  "Regular Hours", "Overtime Hours", "Pay Rate", "Wages", "Incomplete"
];

function parseArgs(argv) {
  const args = { mode: "headed" };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unexpected argument: ${key}`);
    const name = key.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const value = argv[i + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${key}`);
    args[name] = value;
    i += 1;
  }
  for (const name of ["store", "start", "end"]) {
    if (!args[name]) throw new Error(`--${name} is required.`);
  }
  if (!/^\d+$/.test(args.store)) throw new Error("--store must contain digits only.");
  for (const value of [args.start, args.end]) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`Invalid ISO date: ${value}`);
    const parsed = new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
      throw new Error(`Invalid calendar date: ${value}`);
    }
  }
  if (!['headed', 'headless'].includes(args.mode)) throw new Error("--mode must be headed or headless.");
  return args;
}

function flexDate(iso) {
  const [year, month, day] = iso.split("-");
  return `${month}/${day}/${year}`;
}

function clean(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function csvValue(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(rows, columns) {
  return [columns.join(","), ...rows.map((row) => columns.map((column) => csvValue(row[column])).join(","))].join("\n") + "\n";
}

async function fillFirstVisible(page, selectors, value) {
  for (const selector of selectors) {
    const field = page.locator(selector).first();
    if (!(await field.count())) continue;
    try {
      await field.waitFor({ state: "visible", timeout: 2000 });
      await field.fill(value);
      return true;
    } catch { /* try next selector */ }
  }
  return false;
}

async function locatePayroll(page, requestedUrl) {
  if (requestedUrl) return requestedUrl;
  try {
    await page.goto("https://fms.flexepos.com/FlexeposWeb/home.seam", { waitUntil: "domcontentloaded" });
    const storeTools = page.locator(".menu-header", { hasText: "Store Tools" }).first();
    await storeTools.waitFor({ state: "visible", timeout: 10000 });
    await storeTools.click();
    const payroll = page.getByRole("link", { name: "Payroll", exact: true }).first();
    await payroll.waitFor({ state: "visible", timeout: 5000 });
    const href = await payroll.getAttribute("href");
    if (href) return new URL(href, page.url()).href;
  } catch (error) {
    console.warn(`[navigation] Payroll menu unavailable; using direct URL: ${error.message}`);
  }
  return DEFAULT_REPORT_URL;
}

async function fillParameters(page, args) {
  const storeOk = await fillFirstVisible(page, [
    "#parameters\\:store", "input[name*='store' i]", "input[id*='store' i]"
  ], args.store);
  const startOk = await fillFirstVisible(page, [
    "#parameters\\:startDateCalendarInputDate", "#parameters\\:startDateInputDate",
    "input[name*='startDate' i]", "input[id*='startDate' i]"
  ], flexDate(args.start));
  const endOk = await fillFirstVisible(page, [
    "#parameters\\:endDateCalendarInputDate", "#parameters\\:endDateInputDate",
    "input[name*='endDate' i]", "input[id*='endDate' i]"
  ], flexDate(args.end));
  if (!storeOk || !startOk || !endOk) throw new Error("Could not find the store and start/end date fields.");

  let overtime = page.getByLabel(/calculate.*overtime/i).first();
  if (!(await overtime.count())) {
    overtime = page.locator("input[type='checkbox'][name*='overtime' i], input[type='checkbox'][id*='overtime' i]").first();
  }
  if (!(await overtime.count())) {
    overtime = page.locator("td.label", { hasText: /calculates overtime/i })
      .first().locator("xpath=following-sibling::td[1]//input[@type='checkbox']");
  }
  await overtime.waitFor({ state: "visible", timeout: 5000 });
  if (!(await overtime.isChecked())) await overtime.check();
  if (!(await overtime.isChecked())) throw new Error("Calculate Overtime checkbox could not be enabled.");
}

async function scrapeResults(page, args) {
  const expectedRange = `${flexDate(args.start)} - ${flexDate(args.end)}`;
  await page.getByText(new RegExp(`Store\\s+${args.store}\\s+payroll`, "i")).first()
    .waitFor({ state: "visible", timeout: 30000 });
  const body = clean(await page.locator("body").innerText());
  if (!body.includes(expectedRange)) throw new Error(`Payroll date range mismatch; expected ${expectedRange}.`);

  const result = await page.locator("table").evaluateAll((tables) => {
    const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
    const wanted = ["Employee Name", "Employee Number", "Regular Hours", "Overtime Hours", "Pay Rate", "Wages", "Incomplete"];
    for (const table of tables) {
      const rows = [...table.querySelectorAll("tr")];
      const headerIndex = rows.findIndex((tr) => {
        const cells = [...tr.cells].map(text);
        return wanted.every((heading) => cells.includes(heading));
      });
      if (headerIndex < 0) continue;
      const data = [];
      let total = null;
      for (const tr of rows.slice(headerIndex + 1)) {
        const cells = [...tr.cells].map(text);
        if (!cells.length) continue;
        if (/^Total$/i.test(cells[0])) { total = cells; continue; }
        if (/Average Wages/i.test(cells.join(" "))) continue;
        if (cells.length >= wanted.length) {
          const employeeLink = tr.querySelector("a");
          data.push({ cells: cells.slice(0, wanted.length), href: employeeLink?.href || "" });
        }
      }
      return { data, total };
    }
    return null;
  });
  if (!result || !result.data.length) throw new Error("No payroll employee rows were found.");

  const averageMatches = [...body.matchAll(/Average Wages:\s*\$?([\d,.()-]+)/gi)];
  return {
    rows: result.data.map(({ cells }) => Object.fromEntries(COLUMNS.map((column, index) => [column,
      index === 0 ? args.store : index === 1 ? args.start : index === 2 ? args.end : cells[index - 3] ?? ""
    ]))),
    employees: result.data.map(({ cells, href }) => ({
      employeeName: cells[0], employeeNumber: cells[1], href
    })),
    total: result.total,
    averageWages: averageMatches.length ? averageMatches.at(-1)[1] : ""
  };
}

async function browserBackTo(page, locator, description) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.goBack({ waitUntil: "domcontentloaded" }).catch(() => null);
    if (await locator.count()) {
      await locator.first().waitFor({ state: "visible", timeout: 10000 });
      return;
    }
  }
  throw new Error(`Browser Back did not return to ${description}.`);
}

async function scrapeEmployeeTimeclocks(page, employees, args, debugDir) {
  const records = [];
  const payrollHeading = page.getByText(new RegExp(`Store\\s+${args.store}\\s+payroll`, "i"));
  for (const employee of employees) {
    if (!employee.href) {
      records.push({
        employeeName: employee.employeeName,
        employeeNumber: employee.employeeNumber,
        payPeriod: `${flexDate(args.start)} - ${flexDate(args.end)}`,
        status: "no_employee_link",
        timeclocks: []
      });
      continue;
    }
    try {
      const link = page.getByRole("link", { name: employee.employeeName, exact: true }).first();
      await link.waitFor({ state: "visible", timeout: 10000 });
      await Promise.all([
        page.waitForLoadState("domcontentloaded").catch(() => {}),
        link.click()
      ]);

      const adjust = page.locator("input[type='submit'][value='Adjust Time']").first();
      await adjust.waitFor({ state: "visible", timeout: 10000 });
      await Promise.all([
        page.waitForLoadState("domcontentloaded").catch(() => {}),
        adjust.click()
      ]);
      await page.getByText("Adjusted Start Time", { exact: true }).first()
        .waitFor({ state: "visible", timeout: 10000 });

      const detail = await page.locator("table").evaluateAll((tables) => {
        const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
        const wanted = ["Date", "Start Time", "Adjusted Start Time", "End Time", "Adjusted End Time", "Worked Time"];
        for (const table of tables) {
          const rows = [...table.querySelectorAll("tr")];
          const headerIndex = rows.findIndex((tr) => {
            const cells = [...tr.cells].map(text);
            return wanted.every((heading) => cells.includes(heading));
          });
          if (headerIndex < 0) continue;
          return rows.slice(headerIndex + 1).map((tr) => [...tr.cells].map(text).slice(0, wanted.length))
            .filter((cells) => cells.length && /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(cells[0]));
        }
        return null;
      });
      if (!detail) throw new Error("Adjust Time table was not found.");

      const bodyText = clean(await page.locator("body").innerText());
      const payPeriodMatch = bodyText.match(/Pay period:\s*(\d{1,2}\/\d{1,2}\/\d{4}\s*-\s*\d{1,2}\/\d{1,2}\/\d{4})/i);
      const expectedPayPeriod = `${flexDate(args.start)} - ${flexDate(args.end)}`;
      if (!payPeriodMatch || payPeriodMatch[1] !== expectedPayPeriod) {
        throw new Error(`Employee pay period mismatch; expected ${expectedPayPeriod}.`);
      }
      records.push({
        employeeName: employee.employeeName,
        employeeNumber: employee.employeeNumber,
        payPeriod: payPeriodMatch[1],
        status: "success",
        timeclocks: detail.map((cells) => ({
          date: cells[0] || "",
          startTime: cells[1] || "",
          adjustedStartTime: cells[2] || "",
          endTime: cells[3] || "",
          adjustedEndTime: cells[4] || "",
          workedTime: cells[5] || ""
        }))
      });

      await browserBackTo(page, page.getByText(/worked hours/i), "the employee hours page");
      await browserBackTo(page, payrollHeading, "the store payroll summary");
      console.log(`[timeclocks] ${employee.employeeNumber || employee.employeeName}`);
    } catch (error) {
      const safeEmployee = `${employee.employeeNumber || employee.employeeName}`.replace(/[^0-9A-Za-z_-]/g, "_");
      await page.screenshot({ path: path.join(debugDir, `employee_${safeEmployee}.png`), fullPage: true }).catch(() => {});
      await fs.writeFile(path.join(debugDir, `employee_${safeEmployee}.html`), await page.content(), "utf8").catch(() => {});
      throw new Error(`Could not scrape timeclocks for employee ${employee.employeeNumber || employee.employeeName}: ${error.message}`);
    }
  }
  return records;
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const outputDir = path.resolve(args.outputDir || path.join(repoRoot, "flexepos", "runs", `${args.start}_${args.end}`, "payroll"));
  const debugDir = path.join(outputDir, "debug");
  await fs.mkdir(debugDir, { recursive: true });
  const outputPath = path.join(outputDir, "payroll.csv");
  const summaryPath = path.join(outputDir, "payroll_summary.json");
  const timeclocksPath = path.join(outputDir, "employee_timeclocks.json");
  const { browser, page } = await openAuthenticatedContext({
    statePath: path.resolve(repoRoot, args.authState || "flexepos/.auth/session-4.json"),
    headless: args.mode === "headless"
  });
  try {
    const reportUrl = await locatePayroll(page, args.reportUrl);
    await page.goto(reportUrl, { waitUntil: "domcontentloaded" });
    await fillParameters(page, args);
    const submit = page.getByRole("button", { name: /^submit$/i }).first();
    await Promise.all([page.waitForLoadState("networkidle").catch(() => {}), submit.click()]);
    const result = await scrapeResults(page, args);
    await fs.writeFile(outputPath, toCsv(result.rows, COLUMNS), "utf8");
    await fs.writeFile(summaryPath, JSON.stringify({
      store: args.store, startDate: args.start, endDate: args.end,
      employeeCount: result.rows.length, averageWages: result.averageWages, total: result.total
    }, null, 2) + "\n", "utf8");
    const timeclocks = await scrapeEmployeeTimeclocks(page, result.employees, args, debugDir);
    await fs.writeFile(timeclocksPath, JSON.stringify({
      store: args.store,
      startDate: args.start,
      endDate: args.end,
      employees: timeclocks
    }, null, 2) + "\n", "utf8");
    console.log(`Payroll CSV     : ${outputPath}`);
    console.log(`Payroll summary : ${summaryPath}`);
    console.log(`Timeclocks JSON : ${timeclocksPath}`);
  } catch (error) {
    const base = `${args.store}_${args.start}_${args.end}`;
    await page.screenshot({ path: path.join(debugDir, `${base}.png`), fullPage: true }).catch(() => {});
    await fs.writeFile(path.join(debugDir, `${base}.html`), await page.content(), "utf8").catch(() => {});
    throw error;
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
