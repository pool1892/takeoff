#!/usr/bin/env node
import { existsSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { readIdentity, saveBuyerIdentity } from "./identity.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const root = realpathSync(path.resolve(directory, "../.."));
const cli = path.join(directory, "node_modules/ambiguous/dist/index.js");
const args = process.argv.slice(2);

function fail(message) {
  console.error(`Ambiguous: ${message}`);
  process.exit(1);
}

// This guard prevents accidental host launches. Docker supplies the isolation.
if (process.env.TAKEOFF_SANDBOX !== "1" || !existsSync("/.dockerenv")) {
  fail("run this command through the Takeoff container launcher.");
}
const home = realpathSync(process.env.HOME || "/");
if (!home.startsWith(`${root}${path.sep}`)) {
  fail("HOME must be inside the mounted Takeoff repository.");
}
process.chdir(root);
process.env.XDG_CONFIG_HOME = path.join(home, ".config");
process.env.XDG_CACHE_HOME = path.join(home, ".cache");
process.env.AMBI_API_URL ||= "https://api.ambiguous.ai";
const origin = process.env.AMBI_API_URL.replace(/\/+$/, "");
if (!["https://api.ambiguous.ai", "https://app.ambiguous.ai"].includes(origin)) {
  fail("AMBI_API_URL must be a verified Ambiguous production origin.");
}
process.env.AMBI_API_URL = origin;

const publicCommand = args.length === 0 || args.includes("--help") ||
  args.includes("-h") || args[0] === "--version" || args[0] === "-V" ||
  args[0] === "catalog";

if (!publicCommand) {
  let identity;
  try {
    identity = await readIdentity({
      origin,
      token: process.env.AMBI_API_TOKEN,
      workspaceId: process.env.TAKEOFF_AMBIGUOUS_WORKSPACE_ID,
      userId: process.env.TAKEOFF_AMBIGUOUS_USER_ID,
      workspaceRef: process.env.TAKEOFF_AMBIGUOUS_WORKSPACE_REF,
      identify: ["identify", "connect"].includes(args[0]),
    });
  } catch (error) {
    fail(error.message);
  }
  if (args[0] === "connect") {
    try {
      saveBuyerIdentity(root, identity);
    } catch (error) {
      console.error(JSON.stringify(identity, null, 2));
      fail(error.code ? `could not save local configuration (${error.code}); no workspace write occurred.` : error.message);
    }
    console.log(JSON.stringify({ ...identity, connected: true, config: ".local/hermes/.env" }, null, 2));
    process.exit(0);
  }
  if (["check", "identify"].includes(args[0])) {
    console.log(JSON.stringify(identity, null, 2));
    process.exit(0);
  }
}

if (!existsSync(cli)) fail("CLI is not installed; run the repo-local npm ci command in docs/ambiguous.md.");
if (args[0] === "auth" || args[0] === "whoami" || args[0] === "config") {
  if (!publicCommand) fail("use `check` for identity; credentials come from the isolated buyer environment.");
}
if (args[0] === "notifications" && ["setup", "recovery"].includes(args[1]) && !publicCommand) {
  fail("use explicit polling; the upstream setup helper may install a host service.");
}
const command = args[0] === "poll" && publicCommand ? ["notifications", "poll", "--help"] : args[0] === "poll" ? [
  "notifications", "poll", "--format", "hermes",
  "--expected-user", process.env.TAKEOFF_AMBIGUOUS_USER_ID,
  "--expected-workspace", process.env.TAKEOFF_AMBIGUOUS_WORKSPACE_ID,
  ...args.slice(1),
] : args;
const child = spawn(process.execPath, [cli, ...command], { stdio: "inherit", env: process.env });
child.on("error", () => fail("could not start the installed CLI."));
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
