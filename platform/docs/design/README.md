# Design documents

Technical designs for the Prometheus platform. These files are the source of truth;
where a design started on Confluence, the Confluence page now points here.

Diagrams are inline [mermaid](https://mermaid.js.org/) blocks, so edit them like any
other text.

| Document | Status | Summary |
| --- | --- | --- |
| [User Proof Chain: Passkey-Signed Approvals and Session-Bound Turns](user-proof-chain.md) | Design, not built | How the platform proves which user is behind an agent action and that they approved it: IdP MFA login, a passkey-certified session key for turns, and passkey- or IdP-signed approvals. |
| [ADR-006 Agent Settings: Declared in the Agent Card, Overridden per User](agent-settings.md) | Proposed, not built | Agents declare typed, grouped settings in their card; the platform generates the settings UI, stores per-user overrides, and serves effective values to agents over `/v1/agent-settings`, identified by mTLS when available. |
| [Hierarchical Orchestration: Sub-Orchestrators as Agents](hierarchical-orchestration.md) | Design, not built | An SDK orchestrator base class and config-driven domain sub-orchestrators that nest to any depth, with brief-based context passing, call-chain metadata, and routing of approvals and INPUT_REQUIRED across levels. |
