variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "name_suffix" {
  description = "Appended to every alert rule name, for example the CAF base name."
  type        = string
}

variable "action_group_name" {
  type = string
}

variable "action_group_short_name" {
  description = "Up to 12 characters; shown in SMS and email notifications."
  type        = string

  validation {
    condition     = length(var.action_group_short_name) <= 12
    error_message = "action_group_short_name must be at most 12 characters."
  }
}

variable "alert_email" {
  description = "Optional on-call address. Empty = alerts still fire in Azure Monitor but notify nobody."
  type        = string
  default     = ""
}

variable "log_analytics_id" {
  type = string
}

variable "app_insights_id" {
  type = string
}

variable "metric_alerts" {
  description = "Metric alert rules keyed by a short name."
  type = map(object({
    scope       = string
    namespace   = string
    metric      = string
    aggregation = string
    operator    = string
    threshold   = number
    severity    = number
    description = string
  }))
  default = {}
}

variable "log_alerts" {
  description = "KQL alert rules on Application Insights, keyed by a short name; fire when the row count exceeds threshold in 15 minutes."
  type = map(object({
    query       = string
    threshold   = number
    severity    = number
    description = string
  }))
  default = {}
}

variable "diagnostic_targets" {
  description = "Resources whose allLogs + AllMetrics go to the Log Analytics workspace, keyed by a static name."
  type        = map(string)
  default     = {}
}
