#!/usr/bin/env node
// One-time, explicitly authorized setup of Christoph's managed Takeoff agent.
import { closeSync, constants, existsSync, fchmodSync, fstatSync, fsyncSync, lstatSync, openSync, readFileSync, realpathSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const WORKSPACE = "9ab01362-770d-4f8c-98a5-c431e5e44dac";
const MANAGER = "9df6ad27-165e-4534-8e26-800b5a33ab6a";
const NAME = "Takeoff Hermes";
const USERNAME = "takeoff-hermes";
export const SCOPES = [
  "tasks.read", "tasks.write", "notifications.read", "notifications.write",
  "chat.read", "chat.write", "mail.read", "mail.write", "mail.send",
  "documents.read", "documents.write", "drive.read", "drive.write", "users.view", "settings.view",
];
const uuid = (value) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
class SetupError extends Error {}
function requireValue(condition, message) { if (!condition) throw new SetupError(message); }
function safeUser(user) {
  return { user_id: user.id, display_name: user.display_name, username: user.username, type: user.type };
}

function credentialFile(root) {
  const target = path.join(root, ".local/hermes/.env");
  for (const entry of [root, path.join(root, ".local"), path.dirname(target), target]) {
    requireValue(!lstatSync(entry).isSymbolicLink(), "Refusing a symlink in the credential path.");
  }
  return target;
}

function replaceToken(root, token) {
  const target = credentialFile(root);
  const descriptor = openSync(target, constants.O_RDONLY | constants.O_NOFOLLOW);
  let previous;
  let contents;
  try {
    previous = fstatSync(descriptor);
    requireValue(previous.isFile(), "Credential path must be a regular file.");
    contents = readFileSync(descriptor, "utf8");
  } finally { closeSync(descriptor); }
  contents = contents.replace(/^[\t ]*(?:export[\t ]+)?AMBI_API_TOKEN[\t ]*=.*(?:\r?\n|$)/gm, "");
  if (contents && !contents.endsWith("\n")) contents += "\n";
  contents += `AMBI_API_TOKEN=${JSON.stringify(token)}\n`;
  const temporary = path.join(path.dirname(target), `.env-provision-${randomUUID()}.tmp`);
  let output;
  try {
    output = openSync(temporary, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY, 0o600);
    writeFileSync(output, contents, "utf8");
    fchmodSync(output, 0o600);
    fsyncSync(output);
    closeSync(output);
    output = undefined;
    const current = lstatSync(target);
    requireValue(!current.isSymbolicLink() && current.ino === previous.ino && current.size === previous.size && current.mtimeMs === previous.mtimeMs,
      "Credential file changed during setup; no replacement saved.");
    renameSync(temporary, target);
  } finally {
    if (output !== undefined) closeSync(output);
    try { unlinkSync(temporary); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
}

export async function provision({ root, token, origin = "https://api.ambiguous.ai", fetcher = fetch, log = console.log }) {
  const state = { stage: "validate bootstrap identity", agent_id: null, initial_key_id: null, scoped_key_id: null, credential_saved: false, initial_key_revoked: false };
  const request = async (method, endpoint, body, credential = token) => {
    let response;
    try {
      response = await fetcher(`${origin}${endpoint}`, {
        method, headers: { Authorization: `Bearer ${credential}`, "Content-Type": "application/json", "API-Version": "1" },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout(30_000), redirect: "error",
      });
    } catch {
      throw new SetupError(`${method} ${endpoint}: network failure; mutation outcome may be unknown. No automatic retry.`);
    }
    if (!response.ok) {
      throw new SetupError(`${method} ${endpoint}: HTTP ${response.status}. Provisioning requires workspace admin/owner plus users.manage and api_keys.manage; key inspection may require api_keys.view. No permission changes attempted.`);
    }
    if (response.status === 204) return null;
    try { return await response.json(); } catch { throw new SetupError(`${method} ${endpoint}: invalid JSON response; no body displayed.`); }
  };
  try {
    requireValue(["https://api.ambiguous.ai", "https://app.ambiguous.ai"].includes(origin), "Unverified API origin.");
    requireValue(typeof token === "string" && token.startsWith("ak_") && !/[\r\n\0]/.test(token), "A valid bootstrap API key is required in the isolated environment.");
    credentialFile(root);
    const me = await request("GET", "/api/users/me");
    const workspace = await request("GET", "/api/workspace");
    requireValue(me.id === MANAGER && me.workspace_id === WORKSPACE && me.type === "human", "Bootstrap key is not Christoph's verified contractor identity in takeoffAI.");
    requireValue([workspace.name, workspace.slug].some((value) => typeof value === "string" && value.toLowerCase() === "takeoffai"), "Workspace name/slug does not match takeoffAI.");

    state.stage = "check for an existing Takeoff agent";
    let cursor;
    const seenCursors = new Set();
    for (let page = 0; page < 20; page++) {
      const result = await request("GET", `/api/admin/users?type=agent&limit=500${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      requireValue(Array.isArray(result.data) && typeof result.has_more === "boolean", "Invalid workspace user list.");
      const existing = result.data.filter((user) =>
        /^takeoff/i.test(user.display_name || "") || /^takeoff/i.test(user.username || ""));
      if (existing.length) {
        log(JSON.stringify({ existing_takeoff_agents: existing.map(safeUser) }));
        throw new SetupError("A Takeoff identity already exists. Inspect it before provisioning; no duplicate created.");
      }
      if (!result.has_more) break;
      requireValue(page < 19 && typeof result.next_cursor === "string" && result.next_cursor && !seenCursors.has(result.next_cursor), "Cannot completely inspect existing agents; no agent created.");
      cursor = result.next_cursor;
      seenCursors.add(cursor);
    }

    state.stage = "create Christoph's managed Takeoff Hermes agent";
    const created = await request("POST", "/api/admin/users/provision-agent", {
      display_name: NAME, username: USERNAME, role: "member", manager_user_id: MANAGER,
    });
    requireValue(uuid(created.user?.id), "Provisioning response did not contain an agent UUID; inspect workspace before retrying.");
    state.agent_id = created.user.id;
    requireValue(created.user.type === "agent" && created.user.username === USERNAME && created.user.role === "member", "Provisioned identity does not match requested agent/member properties.");
    requireValue(typeof created.api_key === "string" && created.api_key.startsWith("ak_"), "Provisioning did not return the initial API key.");

    state.stage = "identify the newly generated initial key";
    const initial = await request("GET", `/api/admin/api-keys?user_id=${state.agent_id}`);
    requireValue(Array.isArray(initial.data) && initial.data.length === 1, "Could not uniquely identify the initial key on the newly created agent; no key revoked.");
    const firstKey = initial.data[0];
    requireValue(uuid(firstKey.id) && firstKey.user_id === state.agent_id && (!firstKey.key_prefix || created.api_key.startsWith(firstKey.key_prefix)), "Initial key metadata did not match the newly created agent/key; no key revoked.");
    state.initial_key_id = firstKey.id;

    state.stage = "create the scoped runtime key";
    const scoped = await request("POST", "/api/admin/api-keys", {
      user_id: state.agent_id, name: "Takeoff Hermes hackathon", scopes: SCOPES, rate_limit: 100,
    });
    requireValue(uuid(scoped.key?.id), "Scoped key response did not contain a key UUID.");
    state.scoped_key_id = scoped.key.id;
    requireValue(scoped.key.user_id === state.agent_id && Array.isArray(scoped.key.scopes) &&
      JSON.stringify([...scoped.key.scopes].sort()) === JSON.stringify([...SCOPES].sort()), "Returned runtime key scopes/user differ from the requested values; no credential installed.");
    requireValue(typeof scoped.raw_key === "string" && scoped.raw_key.startsWith("ak_") && !/[\r\n\0]/.test(scoped.raw_key), "Scoped key response did not contain a valid credential.");

    state.stage = "verify the scoped runtime identity";
    const agent = await request("GET", "/api/users/me", undefined, scoped.raw_key);
    requireValue(agent.id === state.agent_id && agent.workspace_id === WORKSPACE && agent.type === "agent", "Scoped key resolves to an unexpected identity; no credential installed.");
    const agentWorkspace = await request("GET", "/api/workspace", undefined, scoped.raw_key);
    requireValue([agentWorkspace.name, agentWorkspace.slug].some((value) => typeof value === "string" && value.toLowerCase() === "takeoffai"), "Scoped key workspace reference mismatch; no credential installed.");

    state.stage = "save only the scoped runtime credential";
    replaceToken(root, scoped.raw_key);
    state.credential_saved = true;
    state.stage = "revoke only the just-created initial key";
    await request("DELETE", `/api/admin/api-keys/${state.initial_key_id}`);
    const remaining = await request("GET", `/api/admin/api-keys?user_id=${state.agent_id}`);
    requireValue(Array.isArray(remaining.data) && !remaining.data.some((key) => key.id === state.initial_key_id) && remaining.data.some((key) => key.id === state.scoped_key_id), "Could not verify initial-key revocation; inspect the reported key IDs.");
    state.initial_key_revoked = true;
    state.stage = "complete";
    const result = { ...state, workspace_id: WORKSPACE, manager_user_id: MANAGER, display_name: NAME, username: USERNAME, scope_count: SCOPES.length };
    log(JSON.stringify(result, null, 2));
    return result;
  } catch (error) {
    log(JSON.stringify({ provisioning_state: state }));
    throw new SetupError(error instanceof SetupError ? error.message : "Local setup operation failed; credentials and response bodies were not displayed.");
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] !== "--apply") {
    console.log("Creates Christoph's managed Takeoff Hermes member agent in verified takeoffAI, installs a 15-scope runtime key, and revokes only its automatically generated initial key. Run inside the Takeoff container with --apply after authorization.");
  } else {
    try {
      requireValue(process.env.TAKEOFF_SANDBOX === "1" && existsSync("/.dockerenv"), "Use the Takeoff container launcher.");
      const root = realpathSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../.."));
      requireValue(realpathSync(process.env.HOME || "/").startsWith(`${root}${path.sep}`), "HOME must remain inside the Takeoff repository.");
      await provision({ root, token: process.env.AMBI_API_TOKEN, origin: (process.env.AMBI_API_URL || "https://api.ambiguous.ai").replace(/\/+$/, "") });
    } catch (error) {
      console.error(`Takeoff provisioning: ${error instanceof SetupError ? error.message : "Local runtime initialization failed."}`);
      process.exitCode = 1;
    }
  }
}
