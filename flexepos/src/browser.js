"use strict";

const fs = require("fs/promises");
const path = require("path");
const { chromium } = require("playwright");

const BASE_URL = "https://fms.flexepos.com/FlexeposWeb/";
const LOGIN_URL = new URL("home.seam", BASE_URL).href;
const LOGGED_IN_SELECTOR = "a:has-text('Logout')";
const DEFAULT_ENV_PATHS = [".env", "flexepos/.env"];

async function exists(filePath) {
  return fs.access(filePath).then(() => true).catch(() => false);
}

async function isAuthenticated(page) {
  return page.locator(LOGGED_IN_SELECTOR).first()
    .waitFor({ state: "visible", timeout: 5000 })
    .then(() => true)
    .catch(() => false);
}

function parseEnv(text) {
  const values = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    const [, key, rawValue] = match;
    let value = rawValue.trim();
    if (
      (value.startsWith("\"") && value.endsWith("\"")) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

async function loadEnv(paths = DEFAULT_ENV_PATHS) {
  const values = {};
  for (const envPath of paths) {
    try {
      Object.assign(values, parseEnv(await fs.readFile(path.resolve(envPath), "utf8")));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  return values;
}

async function fillCredentialsFromEnv(page, env) {
  const username = env.FLEXE_USERNAME || env.FLEXEPOS_USERNAME;
  const password = env.FLEXE_PASSWORD || env.FLEXEPOS_PASSWORD;
  if (!username || !password) return false;

  const userNameField = page.getByLabel(/user\s*name/i).first();
  const passwordField = page.getByLabel(/password/i).first();
  await userNameField.waitFor({ state: "visible", timeout: 10000 });
  await userNameField.fill(username);
  await passwordField.fill(password);

  const loginButton = page.getByRole("button", { name: /log\s*in|login|sign\s*in/i }).first();
  await loginButton.click();
  console.log("Filled FlexePOS username/password from .env. Complete MFA if requested.");
  return true;
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
    const env = await loadEnv(options.envPaths);
    let attemptedEnvLogin = false;
    try {
      attemptedEnvLogin = await fillCredentialsFromEnv(page, env);
    } catch (error) {
      console.warn(`Could not autofill FlexePOS login from .env: ${error.message}`);
    }
    if (headless && !attemptedEnvLogin) {
      await browser.close();
      throw new Error(
        "The saved FlexePOS session is missing or expired, and FLEXE_USERNAME/FLEXE_PASSWORD were not available for headless login."
      );
    }
    if (!headless) {
      console.log("Log in to FlexePOS in the visible browser window if needed. Complete MFA if requested.");
    }
    console.log("The run will continue automatically after the Logout link appears.");
    try {
      await page.locator(LOGGED_IN_SELECTOR).first().waitFor({
        state: "visible",
        timeout: Number(options.loginTimeoutMs || 10 * 60 * 1000)
      });
    } catch (error) {
      if (headless) {
        await browser.close();
        throw new Error(
          "FlexePOS headless login did not reach the logged-in state. Check FLEXE_USERNAME/FLEXE_PASSWORD or run headed once to inspect the login page."
        );
      }
      throw error;
    }
  }

  await fs.mkdir(path.dirname(statePath), { recursive: true });
  await context.storageState({ path: statePath });
  return { browser, context, page, statePath };
}

module.exports = { BASE_URL, openAuthenticatedContext };
