# RAG chat integration (agent protocol v2)

This increment connects PR17's knowledge storage to the existing **single-agent**
model/tools graph. It does not add agents, change identity roles, migrate a live
database or call an external embedding service. All bundled policies are
**synthetic demo data**, not the policies of a real retailer.

## What is connected

1. The fixed model tool contract exposes `search_knowledge({"query": "..."})`.
2. `BoundTools` supplies the authenticated tenant's PostgreSQL `BusinessStore`.
   The model cannot supply a tenant, customer, SQL, path, URL or result limit.
3. The repository searches active knowledge documents in that tenant's schema.
4. The tool returns bounded excerpts with server-created citation IDs and hashes.
5. The final answer references those IDs as `[KB:<24 lowercase hex characters>]`.
6. The backend checks membership in **this turn's actual retrieved evidence**.
   Only referenced excerpts become the response's `sources` array.
7. The UI displays a closed-by-default **Nguon tham khao / Sources** disclosure
   below the response, independently of the technical process-trace toggle.

Sources contain `citation_id`, `title`, `source_key`, `excerpt`,
`content_sha256` (hash of the exact excerpt) and `truncated`. The model does not
supply a sources array. Source URIs and arbitrary metadata are not returned to the
browser, and the renderer creates text nodes, never HTML or external source links.

## Retrieval and token budgets

The embedder remains **feature-hash-v1**, a 384-dimensional deterministic lexical
feature baseline. It is NOT a neural multilingual embedding model. This PR does
not claim production-quality semantic retrieval or benchmark improvements.

The model-facing adapter uses the existing hybrid ranker, a `0.15` score cutoff,
and a literal normalized-token overlap guard to reduce irrelevant hash matches.
These are heuristics, not confidence probabilities or a guarantee of relevance.
At most two knowledge searches, three returned excerpts per search, 1,100
characters per excerpt, 2,800 serialized characters per reply and 3,600 cumulative
serialized characters of successful retrieval output are allowed per turn.
Existing global graph/model/tool budgets remain in effect. Broad queries can
return incomplete evidence; the assistant must acknowledge missing facts.

## Error and provenance behavior

- Empty/invalid query: `invalid_knowledge_query`.
- SQLite or tenant schema v2: `knowledge_not_ready`; no automatic migration/seed.
- Database failures: `knowledge_unavailable` with no DSN or internal exception.
- No sufficiently matching excerpt: `status=no_evidence`, empty `results`.
- Excess retrieval attempts: `knowledge_budget_exceeded`.
- A bracketed KB reference not returned this turn: `knowledge_citation_invalid`.
- Retrieved evidence but no final citation: `knowledge_citation_missing`.

Invalid or missing citations fail **before the final graph node is checkpointed**
and before successful business history is committed. There is no automatic paid
model retry. An explicit retry with the same request ID can reuse saved tool
results and regenerate the final response. Completed-turn replay returns the
original excerpt snapshots even if a document is later changed. Replaying an old
answer is not a fresh policy lookup.

The citation check establishes **provenance only**. It does not prove that every
claim is supported, that the chosen passage is relevant, or that the model used
retrieval whenever it should have. Tool selection and semantic entailment still
need evaluation with real model outputs and reviewed examples. Prompt injection
cannot register new tools or bypass backend ownership/permission/confirmation
checks, but an adversarial passage can still degrade the model's prose.

General shipping/refund/return guidance never establishes the current state,
payment, address, refund or cancellation eligibility of a specific order. Those
facts come from existing owned-order tools. Cancellation still requires reason
selection, a proposal and the separate explicit confirmation action.

## Deployment order and Colab compatibility

**The fixed tool/system contract changes to `retailops-agent-v2`.** An old Colab
proxy advertises v1 and cannot expose the new tool. It is rejected with the
existing `proxy_upgrade_required` error rather than silently pretending RAG works.

Coordinate the rollout in an attended window:

1. Keep the existing database backup and verify the tenant was migrated to schema
   v3 using PR17's attended procedure. Do not rerun migration just for this PR.
   With v2, ordinary order features continue; knowledge reports not ready.
2. Review/merge this PR after CI. Existing CD rolls the web image; it does NOT
   update the separate Colab session or automatically ingest policy documents.
3. Stop the old proxy/tunnel and load the newly generated
   `notebooks/colab_agent.ipynb`. Run its preparation/runtime/proxy cells and check
   `AGENT_MODEL_READY` reports `retailops-agent-v2`. Do not use an old notebook
   saved before this PR. Keep credentials private; update the permitted tunnel
   hostname using the existing model-selector deployment instructions if it changes.
4. During the web/Colab version mismatch, custom chat is deliberately unavailable;
   direct order buttons remain usable. The API adapter uses the shared new contract
   from the web image; switching providers is never automatic.
5. Start a new conversation and run the cases below. Pre-upgrade unfinished graph
   checkpoints return `agent_protocol_changed`; completed business replays remain
   available. No old in-progress graph is silently re-executed with new tools.

The UI has no admin upload or anonymous knowledge endpoint. Ingestion remains an
operator CLI operation from PR17:

```text
python -m retailops knowledge ingest --tenant <tenant> --path <reviewed-directory>
python -m retailops knowledge search --tenant <tenant> --query <question>
```

Check `python -m retailops knowledge --help` for the deployed CLI. Do not point CI
tests at production: PostgreSQL integration requires a disposable database whose
name starts with `retailops_test`.

## Acceptance and evaluation

Automated tests use scripted model responses and a disposable real pgvector DB,
not a paid model and not the live EC2 store. Coverage includes real search-to-chat
sources, cross-tenant isolation, viewer restrictions, invalid model scope/SQL,
no evidence, SQLite/v2 fallback, budgets, invalid/missing citations, checkpoint
retry, completed replay, old protocol rejection, and text-only UI rendering.

After deployment, check with the actual configured model:

| Case | Required behavior |
|---|---|
| Ask the store's return policy | Calls search_knowledge; quotes only supported conditions; valid source disclosure |
| Ask general delivery guidance | Distinguishes the demo policy from a guaranteed delivery date |
| Ask when O-101 arrives | Reads the owned order; does not invent a date from a generic policy |
| Ask an unknown policy or unrelated technical question | Acknowledges missing knowledge/scope; no fabricated source |
| Follow up on a previous policy | Retrieves fresh evidence; no unsupported citation carried from history |
| Ask to cancel a delivered/cancelled order | Existing deterministic eligibility and confirmation rules still apply |
| Hide the process trace | Sources remain independently available |
| Change a document then replay a completed request | Original answer and original excerpt stay together |

Record retrieval hit rate/Recall@k on a reviewed corpus, citation ID validity,
claim-level support, abstention, task completion and latency separately. The green
contract tests are not scores for those model-quality metrics. Neural embeddings,
retrieval tuning/reranking and a reviewed RAG evaluation dataset are later work;
expanded admin/root/guest RBAC and multi-agent orchestration remain deferred.
