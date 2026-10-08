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

variable "name" {
  type = string
}

variable "address_prefix" {
  type    = string
  default = "10.40.0.0/16"
}

variable "dns_zones" {
  description = "logical key -> private DNS zone name"
  type        = map(string)
}
