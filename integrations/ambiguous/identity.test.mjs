import test from "node:test";
import assert from "node:assert/strict";
import { readIdentity, saveBuyerIdentity } from "./identity.mjs";
import { chmodSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const input = {
  origin: "https://api.ambiguous.ai",
  token: "test-token-never-valid",
  workspaceId: "buyer-workspace",
  userId: "buyer-agent",
};
const me = { id: input.userId, workspace_id: input.workspaceId, display_name: "Buyer" };
const json = (value) => ({ ok: true, json: async () => value });

test("identity check uses a read-only endpoint, rejects redirects, and omits the credential", async () => {
  const identity = await readIdentity({ ...input, fetcher: async (url, options) => {
    assert.equal(url, `${input.origin}/api/users/me`);
    assert.equal(options.redirect, "error");
    assert.equal(options.headers.Authorization, `Bearer ${input.token}`);
    return json(me);
  } });
  assert.equal(identity.workspace_id, input.workspaceId);
  assert.equal(JSON.stringify(identity).includes(input.token), false);
});

test("a different workspace or user cannot pass the check", async () => {
  for (const mismatch of [{ ...me, workspace_id: "supplier-workspace" }, { ...me, id: "another-user" }]) {
    await assert.rejects(readIdentity({ ...input, fetcher: async () => json(mismatch) }), /does not match/);
  }
});

test("missing configuration fails before networking", async () => {
  await assert.rejects(readIdentity({ ...input, workspaceId: "", fetcher: () => assert.fail("unexpected request") }), /WORKSPACE_ID/);
});

test("API rejection and unreachable API remain failures without exposing response bodies", async () => {
  await assert.rejects(readIdentity({ ...input, fetcher: async () => ({ ok: false, status: 401 }) }), /HTTP 401/);
  await assert.rejects(readIdentity({ ...input, fetcher: async () => { throw new Error(input.token); } }), (error) => {
    assert.match(error.message, /could not reach/);
    assert.equal(error.message.includes(input.token), false);
    return true;
  });
});

test("identify resolves takeoffAI by complete name or slug, without accepting a similar name", async () => {
  for (const [name, matches] of [["takeoffAI", true], ["takeoffAI supplier", false]]) {
    const identity = await readIdentity({
      ...input, workspaceId: undefined, userId: undefined, identify: true, workspaceRef: "takeoffAI",
      fetcher: async (url) => json(url.endsWith("/me") ? me : { name, slug: "workspace-slug" }),
    });
    assert.equal(identity.workspace_ref_matches, matches);
  }
});

const buyer = {
  type: "agent",
  workspace_id: "11111111-1111-4111-8111-111111111111",
  user_id: "22222222-2222-4222-8222-222222222222",
  expected_workspace_ref: "takeoffAI",
  workspace_ref_matches: true,
};

function configFixture(context, body = "") {
  const root = mkdtempSync(path.join(tmpdir(), "takeoff-ambiguous-connect-"));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, ".local/hermes"), { recursive: true });
  const config = path.join(root, ".local/hermes/.env");
  writeFileSync(config, body);
  return { root, config };
}

test("connect preserves other config lines, replaces only expected IDs, and sets mode 0600", (context) => {
  const unchanged = '# Buyer config\nAMBI_API_TOKEN="test-local-secret"\n\nOPENAI_API_KEY="test-other-secret"\n';
  const { root, config } = configFixture(context,
    unchanged + 'TAKEOFF_AMBIGUOUS_WORKSPACE_ID="old-workspace"\nexport TAKEOFF_AMBIGUOUS_USER_ID="old-user"\n');
  chmodSync(config, 0o644);
  saveBuyerIdentity(root, buyer);
  assert.equal(readFileSync(config, "utf8"), unchanged +
    `TAKEOFF_AMBIGUOUS_WORKSPACE_ID="${buyer.workspace_id}"\nTAKEOFF_AMBIGUOUS_USER_ID="${buyer.user_id}"\n`);
  assert.equal(lstatSync(config).mode & 0o777, 0o600);
  assert.deepEqual(readdirSync(path.dirname(config)), [".env"]);
});

test("connect refuses a human identity, wrong workspace mapping, and invalid IDs without changing config", (context) => {
  const original = 'AMBI_API_TOKEN="test-local-secret"\n';
  const { root, config } = configFixture(context, original);
  for (const invalid of [
    { ...buyer, type: "human" },
    { ...buyer, workspace_ref_matches: false },
    { ...buyer, expected_workspace_ref: "other-workspace" },
    { ...buyer, user_id: "bad\nuser" },
  ]) {
    assert.throws(() => saveBuyerIdentity(root, invalid));
    assert.equal(readFileSync(config, "utf8"), original);
  }
});

test("connect refuses a symlink config file or directory without modifying its target", (context) => {
  const { root, config } = configFixture(context);
  const elsewhere = path.join(root, "other.env");
  writeFileSync(elsewhere, "unchanged\n");
  rmSync(config);
  symlinkSync(elsewhere, config);
  assert.throws(() => saveBuyerIdentity(root, buyer), /symlink/);
  assert.equal(readFileSync(elsewhere, "utf8"), "unchanged\n");
  rmSync(path.join(root, ".local/hermes"), { recursive: true });
  const otherDirectory = path.join(root, "other");
  mkdirSync(otherDirectory);
  writeFileSync(path.join(otherDirectory, ".env"), "unchanged\n");
  symlinkSync(otherDirectory, path.join(root, ".local/hermes"));
  assert.throws(() => saveBuyerIdentity(root, buyer), /symlink/);
  assert.equal(readFileSync(path.join(otherDirectory, ".env"), "utf8"), "unchanged\n");
});
