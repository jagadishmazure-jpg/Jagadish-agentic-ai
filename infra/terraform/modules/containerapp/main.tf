# One Container App (HTTP service or queue worker). The pipeline rolls new images with
# `az containerapp update`, so the image is ignored after creation.
resource "azurerm_container_app" "this" {
  name                         = var.name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.environment_id
  tags                         = merge(var.tags, { "service-name" = var.service_name })
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.registry_server
    identity = var.identity_id
  }

  dynamic "ingress" {
    for_each = var.kind == "http" ? [1] : []
    content {
      external_enabled           = var.external
      target_port                = var.target_port
      transport                  = "auto"
      allow_insecure_connections = !var.external # east-west traffic stays inside the environment
      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name    = "main"
      image   = var.image
      cpu     = var.cpu
      memory  = var.memory
      command = length(var.command) == 0 ? null : var.command

      env {
        name  = "PORT"
        value = tostring(var.target_port)
      }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "liveness_probe" {
        for_each = var.kind == "http" && var.health_path != "" ? [1] : []
        content {
          transport        = "HTTP"
          port             = var.target_port
          path             = var.health_path
          interval_seconds = 30
        }
      }
    }

    dynamic "http_scale_rule" {
      for_each = var.kind == "http" ? [1] : []
      content {
        name                = "http"
        concurrent_requests = tostring(var.concurrent_requests)
      }
    }

    dynamic "custom_scale_rule" {
      for_each = var.kind == "worker" ? [1] : []
      content {
        name             = "queue-length"
        custom_rule_type = "azure-servicebus"
        identity_id      = var.identity_id # KEDA authenticates with the app's own identity
        metadata = {
          namespace    = var.service_bus_namespace
          queueName    = var.queue_name
          messageCount = "5"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
