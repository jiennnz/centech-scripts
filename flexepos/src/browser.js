"use strict";

const fs = require("fs/promises");
const path = require("path");
const { chromium } = require("playwright");

const BASE_URL = "https://fms.flexepos.com/FlexeposWeb/";
const LOGIN_URL = new URL("home.seam", BASE_URL).href;
const LOGGED_IN_SELECTOR = "a:has-text('Logout')";

async function exists(filePath) {
  return fs.access(filePath).then(() => true).catch(() => false);
}

async function isAuthenticated(page) {
  return page.locator(LOGGED_IN_SELECTOR).first()
    .waitFor({ state: "visible", timeout: 5000 })
    .then(() => true)
    .catch(() => false);
}

async function openAuthenticatedContext(options = {}) {
  const statePath = path.resolve(options.statePath || "flexepos/.auth/storage-state.json");
  const headless = options.headless === true;
  const browser = await chromium.launch({
    headless,
    slowMo: Number(options.slowMoMs ?? (headless ? 0 : 100))
  });
  const contextOptions = { viewport: { width: 1440, height: 1000 } };
  if (await exists(statePath)) {
    contextOptions.storageState = statePath;
  }

  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  page.setDefaultTimeout(Number(options.timeoutMs || 30000));
  page.setDefaultNavigationTimeout(Number(options.navigationTimeoutMs || 90000));
  await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" });

  if (!(await isAuthenticated(page))) {
    if (headless) {
      await browser.close();
      throw new Error(
        "The saved FlexePOS session is missing or expired. Run once with --mode headed to log in, then retry headless mode."
      );
    }
    console.log("Log in to FlexePOS in the visible browser window. Complete MFA if requested.");
    console.log("The run will continue automatically after the Logout link appears.");
    await page.locator(LOGGED_IN_SELECTOR).first().waitFor({
      state: "visible",
      timeout: Number(options.loginTimeoutMs || 10 * 60 * 1000)
    });
  }

  await fs.mkdir(path.dirname(statePath), { recursive: true });
  await context.storageState({ path: statePath });
  return { browser, context, page, statePath };
}

module.exports = { BASE_URL, openAuthenticatedContext };
