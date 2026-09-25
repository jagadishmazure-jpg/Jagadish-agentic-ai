import itertools

import pytest

from refund_agent.graph import build_graph
from refund_agent.llm import mock_responder
from refund_agent.services import seed_services
from refund_agent.state import RefundRequest
from shared.llm import MockChatModel


@pytest.fixture
def services():
    return seed_services()


@pytest.fixture
def graph(services):
    # Explicit mock LLM: tests never depend on env vars or the network.
    return build_graph(services, llm=MockChatModel(responder=mock_responder))


_ids = itertools.count(1)


@pytest.fixture
def run(graph):
    """Start a request on a fresh thread; returns (result, config)."""

    def _run(customer, email, order, message):
        n = next(_ids)
        req = RefundRequest(
            request_id=f"req-{n}",
            customer_id=customer,
            email=email,
            order_id=order,
            message=message,
        )
        cfg = {"configurable": {"thread_id": f"thread-{n}"}}
        return graph.invoke({"request": req.model_dump()}, cfg), cfg

    return _run
