import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { provision, SCOPES } from "./provision.mjs";

const workspaceId = "11111111-1111-4111-8111-111111111111";
const managerUserId = "22222222-2222-4222-8222-222222222222";
const agentId = "33333333-3333-4333-8333-333333333333";
const firstKeyId = "44444444-4444-4444-8444-444444444444";
const scopedKeyId = "55555555-5555-4555-8555-555555555555";
const token = "ak_fake_bootstrap_for_offline_tests";
const scopedToken = "ak_fake_scoped_for_offline_tests";
const json = (value) => ({ ok: true, json: async () => value });

function fixture(context) {
  const root = mkdtempSync(path.join(tmpdir(), "takeoff-provision-test-"));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, ".local/hermes"), { recursive: true });
  const config = path.join(root, ".local/hermes/.env");
  const identityConfig = `TAKEOFF_AMBIGUOUS_WORKSPACE_ID=${workspaceId}\nTAKEOFF_AMBIGUOUS_CONTRACTOR_ID=${managerUserId}\n`;
  writeFileSync(config, identityConfig + `AMBI_API_TOKEN=${token}\n`);
  return { root, config, identityConfig };
}

test("provisioning requires explicit valid owner and workspace before networking", async () => {
  for (const invalid of [{ workspaceId: undefined }, { managerUserId: undefined },
    { workspaceId: "bad-id" }, { managerUserId: "bad-id" }]) {
    await assert.rejects(provision({ root: "unused", token, workspaceId, managerUserId, ...invalid,
      log: () => {}, fetcher: () => assert.fail("Unexpected network call") }), /Configure TAKEOFF_AMBIGUOUS_/);
  }
});

test("provisioning refuses a different bootstrap identity without mutation", async (context) => {
  const { root, config } = fixture(context);
  const before = readFileSync(config, "utf8");
  for (const mismatch of [{ id: agentId }, { workspace_id: agentId }, { type: "agent" }]) {
    await assert.rejects(provision({ root, token, workspaceId, managerUserId, log: () => {},
      fetcher: async (url, options) => {
        assert.equal(options.method, "GET");
        return json(url.endsWith("/me")
          ? { id: managerUserId, workspace_id: workspaceId, type: "human", ...mismatch }
          : { name: "takeoffAI" });
      } }), /does not match the configured human contractor and workspace/);
    assert.equal(readFileSync(config, "utf8"), before);
  }
});

test("provisioning binds synthetic configured identities through creation and credential verification", async (context) => {
  const { root, config, identityConfig } = fixture(context);
  const calls = [];
  let revoked = false;
  const logs = [];
  const result = await provision({ root, token, workspaceId, managerUserId, log: (line) => logs.push(line),
    fetcher: async (url, options) => {
      const endpoint = new URL(url).pathname;
      const body = options.body && JSON.parse(options.body);
      calls.push([options.method, endpoint]);
      if (endpoint === "/api/users/me") {
        const scoped = options.headers.Authorization === `Bearer ${scopedToken}`;
        return json({ id: scoped ? agentId : managerUserId, workspace_id: workspaceId,
          type: scoped ? "agent" : "human" });
      }
      if (endpoint === "/api/workspace") return json({ name: "takeoffAI" });
      if (endpoint === "/api/admin/users") return json({ data: [], has_more: false });
      if (endpoint === "/api/admin/users/provision-agent") {
        assert.equal(body.manager_user_id, managerUserId);
        return json({ user: { id: agentId, type: "agent", username: "takeoff-hermes", role: "member" },
          api_key: "ak_fake_initial_for_offline_tests" });
      }
      if (endpoint === "/api/admin/api-keys" && options.method === "GET") {
        assert.equal(new URL(url).searchParams.get("user_id"), agentId);
        return json({ data: [{ id: revoked ? scopedKeyId : firstKeyId, user_id: agentId }] });
      }
      if (endpoint === "/api/admin/api-keys" && options.method === "POST") {
        assert.equal(body.user_id, agentId);
        assert.deepEqual(body.scopes, SCOPES);
        return json({ key: { id: scopedKeyId, user_id: agentId, scopes: SCOPES }, raw_key: scopedToken });
      }
      if (endpoint === `/api/admin/api-keys/${firstKeyId}` && options.method === "DELETE") {
        revoked = true;
        return { ok: true, status: 204 };
      }
      assert.fail("Unexpected mocked request");
    } });
  assert.equal(result.stage, "complete");
  assert.equal(result.workspace_id, workspaceId);
  assert.equal(result.manager_user_id, managerUserId);
  assert.equal(result.agent_id, agentId);
  assert.equal(result.initial_key_revoked, true);
  assert.equal(readFileSync(config, "utf8"), identityConfig + `AMBI_API_TOKEN=${JSON.stringify(scopedToken)}\n`);
  assert.equal(logs.join("").includes(token), false);
  assert.equal(logs.join("").includes(scopedToken), false);
  assert.equal(calls.length, 10);
});
