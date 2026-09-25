"""Project 19: fine-tuning vs prompting for mortgage document-type classification.

Dataset builder (scrub, dedup, leakage check, chat-format JSONL), an offline fine-tuning
path (TF-IDF + logistic regression head, JSON artifact), a comparison harness that runs the
prompted base model and the fine-tuned model through the shared eval pipeline, a model
registry with a promotion gate and rollback, a LangGraph serving graph and an optional,
dry-run-by-default Azure OpenAI fine-tuning script.
"""
