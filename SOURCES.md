# Primary references (checked 2026-09-06)

- Qwen model card: https://huggingface.co/Qwen/Qwen3.5-4B
- Ollama library: https://ollama.com/library/qwen3.5
- Structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- Thinking control: https://docs.ollama.com/capabilities/thinking
- Chat API: https://docs.ollama.com/api/chat
- Model metadata and digest: https://docs.ollama.com/api/tags
- Generation parameters: https://docs.ollama.com/modelfile
- Runtime/memory FAQ: https://docs.ollama.com/faq
- Prefix cache limitations: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
- Cache isolation: https://docs.vllm.ai/en/latest/usage/security/
- Retail policy reference: https://raw.githubusercontent.com/sierra-research/tau2-bench/main/data/tau2/domains/retail/policy.md
- Agent evaluation: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

The bundled synthetic examples are authored for this starter. No tau-bench,
ECom-Bench, or AWM data/code is redistributed. The narrow cancellation-reason
vocabulary is aligned with the referenced Retail policy, but this starter does
NOT implement the original environment, tools, refunds, policy, or evaluator.


Remote inference and deployment references checked on 2026-09-06:

- Colab resource/usage limits: https://research.google.com/colaboratory/faq.html
- ngrok Colab integration: https://ngrok.com/docs/using-ngrok-with/googleColab
- Ollama local authentication: https://docs.ollama.com/api/authentication
- Ollama cloud-disable configuration: https://docs.ollama.com/faq
- GitHub Actions AWS OIDC: https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws
- AWS SSM Run Command: https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html
- ECR permissions: https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-policy-examples.html
- EC2 lifecycle/billing: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html
- Action refs resolved through the connected GitHub integration: actions/checkout v6.1.0 = d23441a48e516b6c34aea4fa41551a30e30af803; aws-actions/configure-aws-credentials v5 = 61815dcd50bd041e203e49132bacad1fd04d2708.
