"use strict";

const { openAuthenticatedContext } = require("./browser");
const { scrapeCsdPage, toComparisonRows } = require("./financial/csd");

module.exports = {
  openAuthenticatedContext,
  scrapeCsdPage,
  toComparisonRows
};
