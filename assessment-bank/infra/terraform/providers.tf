provider "azurerm" {
  features {}
}

# Point this provider at the Entra External ID tenant (the CIAM tenant), not the workforce
# tenant, when you apply. The app registration then lives where learners sign in.
provider "azuread" {}
