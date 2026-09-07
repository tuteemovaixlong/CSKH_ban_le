# Ngrok endpoint conflict recovery

`ERR_NGROK_334` means the account's static dev endpoint is already online elsewhere.

RetailOps must **not** enable ngrok pooling for the Colab inference endpoint: pooling can route requests between stale and current runtimes (including different agent protocol versions).

The generated Colab CELL 3 now:

1. disconnects any known tunnel in the current runtime,
2. kills the local pyngrok agent process,
3. verifies the local RetailOps proxy is `retailops-agent-v2`,
4. retries claiming the HTTPS endpoint with bounded backoff,
5. fails with an explicit instruction if another runtime/process still owns the endpoint.

If retries are exhausted, stop the old notebook/runtime or endpoint in ngrok before rerunning CELL 3. No inference token should be pasted into logs or chat.
