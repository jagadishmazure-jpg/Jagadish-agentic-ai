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

variable "identities" {
  description = "logical key -> identity name"
  type        = map(string)
}
