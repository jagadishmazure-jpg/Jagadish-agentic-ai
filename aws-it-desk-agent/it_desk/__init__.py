"""IT desk playbook agent on Amazon Bedrock (offline mock by default)."""

__all__ = ["ask"]


def ask(*args, **kwargs):
    from it_desk.agent import ask as _ask

    return _ask(*args, **kwargs)
