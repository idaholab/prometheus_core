# Design documents

Technical designs for the Prometheus platform. These files are the source of truth;
where a design started on Confluence, the Confluence page now points here.

Diagrams are inline [mermaid](https://mermaid.js.org/) blocks, so edit them like any
other text.

| Document | Status | Summary |
| --- | --- | --- |
| [Mid-Execution User Approval (`request_user_approval`)](user-approval.md) | Design, not built | An agent pauses inside `_execute`, asks the user an Accept/Decline question, and continues in the same turn; backend-owned record with agent long-poll, 15-minute auto-decline, popup for background runs. |
| [User Proof Chain: Passkey-Signed Approvals and Session-Bound Turns](user-proof-chain.md) | Design, not built | How the platform proves which user is behind an agent action and that they approved it: IdP MFA login, a passkey-certified session key for turns, and passkey- or IdP-signed approvals. |
