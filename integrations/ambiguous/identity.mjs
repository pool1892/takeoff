export async function readIdentity({ origin, token, workspaceId, userId, workspaceRef, identify = false, fetcher = fetch }) {
  if (!token?.trim()) throw new Error("set AMBI_API_TOKEN in the ignored buyer configuration.");
  if (!identify && (!workspaceId?.trim() || !userId?.trim())) {
    throw new Error("set TAKEOFF_AMBIGUOUS_WORKSPACE_ID and TAKEOFF_AMBIGUOUS_USER_ID after identifying the buyer workspace.");
  }
  async function get(endpoint) {
    let response;
    try {
      response = await fetcher(`${origin}${endpoint}`, {
        headers: { Authorization: `Bearer ${token}`, "API-Version": "1" },
        signal: AbortSignal.timeout(30_000),
        redirect: "error",
      });
    } catch {
      throw new Error("identity check could not reach the API; no workspace command ran.");
    }
    if (!response.ok) throw new Error(`identity check returned HTTP ${response.status}; no workspace command ran.`);
    try {
      return await response.json();
    } catch {
      throw new Error("identity check returned invalid JSON; no workspace command ran.");
    }
  }
  const me = await get("/api/users/me");
  if (typeof me.id !== "string" || !me.id || typeof me.workspace_id !== "string" || !me.workspace_id) {
    throw new Error("credential did not resolve to a user with an active workspace.");
  }
  if (!identify && (me.id !== userId || me.workspace_id !== workspaceId)) {
    throw new Error("credential does not match the configured buyer user and workspace; no workspace command ran.");
  }
  const result = {
    authenticated: true,
    user_id: me.id,
    workspace_id: me.workspace_id,
    type: me.type,
    display_name: me.display_name,
    workspace_email: me.workspace_email,
    api_url: origin,
  };
  if (identify) {
    const workspace = await get("/api/workspace");
    result.workspace_name = workspace.name;
    result.workspace_slug = workspace.slug;
    result.expected_workspace_ref = workspaceRef || null;
    result.workspace_ref_matches = Boolean(workspaceRef && [workspace.name, workspace.slug]
      .some((value) => typeof value === "string" && value.toLowerCase() === workspaceRef.toLowerCase()));
  }
  return result;
}

export function saveBuyerIdentity(root, identity) {
  if (identity.expected_workspace_ref?.toLowerCase() !== "takeoffai" || !identity.workspace_ref_matches) {
    throw new Error("workspace name/slug does not match takeoffAI; no local configuration changed.");
  }
  if (identity.type !== "agent") {
    throw new Error("connect requires a dedicated buyer agent identity; no local configuration changed.");
  }
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!uuid.test(identity.workspace_id) || !uuid.test(identity.user_id)) {
    throw new Error("API identity did not contain valid workspace/user UUIDs; no local configuration changed.");
  }
  const directory = path.join(root, ".local/hermes");
  const target = path.join(directory, ".env");
  for (const component of [root, path.join(root, ".local"), directory, target]) {
    if (lstatSync(component).isSymbolicLink()) {
      throw new Error("refusing a symlink in the local buyer configuration path.");
    }
  }
  const descriptor = openSync(target, constants.O_RDONLY | constants.O_NOFOLLOW);
  let original;
  let body;
  try {
    original = fstatSync(descriptor);
    if (!original.isFile()) throw new Error("local buyer configuration must be a regular file.");
    body = readFileSync(descriptor, "utf8");
  } finally {
    closeSync(descriptor);
  }
  body = body.replace(/^[\t ]*(?:export[\t ]+)?TAKEOFF_AMBIGUOUS_(?:WORKSPACE|USER)_ID[\t ]*=.*(?:\r?\n|$)/gm, "");
  if (body && !body.endsWith("\n")) body += "\n";
  body += `TAKEOFF_AMBIGUOUS_WORKSPACE_ID=${JSON.stringify(identity.workspace_id)}\n`;
  body += `TAKEOFF_AMBIGUOUS_USER_ID=${JSON.stringify(identity.user_id)}\n`;

  const temporary = path.join(directory, `.env-connect-${randomUUID()}.tmp`);
  let temporaryDescriptor;
  try {
    temporaryDescriptor = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, 0o600);
    writeFileSync(temporaryDescriptor, body, "utf8");
    fchmodSync(temporaryDescriptor, 0o600);
    fsyncSync(temporaryDescriptor);
    closeSync(temporaryDescriptor);
    temporaryDescriptor = undefined;
    const current = lstatSync(target);
    if (current.isSymbolicLink() || current.ino !== original.ino || current.size !== original.size || current.mtimeMs !== original.mtimeMs) {
      throw new Error("local configuration changed during connect; retry without editing it concurrently.");
    }
    renameSync(temporary, target);
  } finally {
    if (temporaryDescriptor !== undefined) closeSync(temporaryDescriptor);
    try { unlinkSync(temporary); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
}
import {
  closeSync, constants, fchmodSync, fstatSync, fsyncSync, lstatSync, openSync,
  readFileSync, renameSync, unlinkSync, writeFileSync,
} from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
