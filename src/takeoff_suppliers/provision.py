"""Explicit setup of four vendor identities in an existing supplier workspace.

No workspace is created, no invitation is sent, and credentials are saved locally
before a success is reported. This module is never invoked by server startup.
"""
import argparse
import json
import os
from pathlib import Path

import httpx

from .config import DEFAULT_HOME, Settings, private_json


def provision(settings: Settings, client: httpx.Client | None = None) -> dict:
    client = client or httpx.Client(timeout=30)
    base = settings.data.get("ambiguous_base_url", "https://app.ambiguous.ai").rstrip("/")
    headers = {"Authorization": "Bearer " + settings.secret("AMBIGUOUS_SUPPLIER_API_KEY"), "API-Version": "1"}
    response = client.get(base + "/api/users/me", headers=headers)
    response.raise_for_status()
    owner = response.json()
    expected = settings.data.get("supplier_workspace_id")
    if not expected or owner.get("workspace_id") != expected or owner.get("needs_workspace_setup"):
        raise ValueError("Configure the verified existing supplier workspace ID before provisioning.")
    if owner.get("role") not in {"owner", "admin"}:
        raise ValueError("The setup identity must administer the supplier workspace.")
    secret_path = settings.home / "secrets.json"
    secrets = json.loads(secret_path.read_text())
    identities = []
    for vendor_id, vendor in settings.data["vendors"].items():
        key_name = vendor["token_env"]
        if vendor.get("user_id") and settings.secret(key_name, required=False):
            identities.append({"vendor_id": vendor_id, "user_id": vendor["user_id"],
                               "email": vendor.get("email"), "created": False})
            continue
        if vendor.get("provisioning_pending"):
            raise ValueError(f"Prior {vendor_id} provisioning is uncertain; inspect workspace accounts before retrying.")
        vendor["provisioning_pending"] = True
        private_json(settings.home / "config.json", settings.data)
        response = client.post(base + "/api/admin/users/provision-agent", headers=headers, json={
            "display_name": f"Takeoff {vendor_id.title()} Supplier", "username": f"takeoff-{vendor_id}",
            "role": "member", "manager_user_id": owner["id"],
        })
        if response.is_client_error:
            vendor.pop("provisioning_pending", None)
            private_json(settings.home / "config.json", settings.data)
        response.raise_for_status()
        result = response.json()
        # Save the one-time key immediately, never print the complete response.
        secrets[key_name] = result["api_key"]
        private_json(secret_path, secrets)
        user = result["user"]
        vendor.update(user_id=user["id"], email=user.get("workspace_email") or user.get("primary_email") or user.get("email"))
        vendor.pop("provisioning_pending", None)
        private_json(settings.home / "config.json", settings.data)
        identities.append({"vendor_id": vendor_id, "user_id": user["id"], "email": vendor["email"], "created": True})
    return {"workspace_id": expected, "vendors": identities, "credentials": "saved locally; values omitted"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Provision vendor identities in the configured supplier workspace")
    parser.add_argument("--home", default=str(DEFAULT_HOME))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(provision(Settings(args.home)), indent=2))
    except httpx.HTTPStatusError as exc:
        print(f"Provisioning failed: HTTP {exc.response.status_code}. Saved identities are retained.")
        return 1
    except httpx.HTTPError:
        print("Provisioning connection failed. Inspect pending setup before retrying.")
        return 1
    except (ValueError, KeyError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "Unexpected provisioning response; inspect local setup.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
