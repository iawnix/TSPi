"use strict";

const fs = require("node:fs");
const { buildReviewTaskBundle, validateReviewTaskBundle } = require("../src/agents/review/task-packet.cjs");

const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const bundle = buildReviewTaskBundle(input);
validateReviewTaskBundle(bundle.task, bundle.documents);
process.stdout.write(JSON.stringify(bundle));
