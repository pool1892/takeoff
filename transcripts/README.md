# Planning context

Raw conversation transcripts were removed from the final source distribution during
the privacy review. They included personal account and machine references and are
not needed to run or understand the application.

The adopted design is preserved in [AGENTS.md](../AGENTS.md), the
[project README](../README.md), and [demo context](../docs/demo-context.md):

- Start with 25 ambiguous material requirements from a contractor.
- Discover purchasable products and compatible alternatives before negotiation.
- Let buyer and supplier models choose questions, prices, bundles, and tactics;
  code enforces arithmetic, inventory, commercial limits, and approved requirements.
- Use Ambiguous for contractor tasks, questions, supplier mail, and recommendations.
- Keep meaningful substitutions subject to explicit contractor approval.
- Keep the Hermes buyer isolated in Docker, with repository-local state.
- Treat voice as an optional path and distinguish captured runs from authored examples.

This summary replaces the transcript export; it is not a verbatim conversation record.
