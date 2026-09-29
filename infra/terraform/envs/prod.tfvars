# prod: one warm replica, no log cap, more model capacity, purge protection.
environment                = "prod"
location                   = "eastus2"
instance                   = "001"
cost_profile               = "standard"
live_llm                   = false
key_vault_purge_protection = true
