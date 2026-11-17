# `assessment-bank/tests`

Offline tests. No Entra tenant and no Cosmos account.

| File | What it does |
|---|---|
| [`test_api.py`](test_api.py) | Sign-in, a passing quiz and lab, and progress isolated per learner. |
| [`test_auth_store.py`](test_auth_store.py) | An RS256 External ID token, and the Cosmos AAD request shape. |
| [`test_bank.py`](test_bank.py) | All eight modules load, and GET hides the answer keys. |
| [`test_iac.py`](test_iac.py) | Terraform and Bicep agree on serverless Cosmos, Entra and scale-to-zero. |
| [`test_labs.py`](test_labs.py) | Reference solutions pass pytest; a wrong function and a syntax error do not. |
