variable "site" {
  description = "Validated identity and environment for this homelab."
  type = object({
    name        = string
    domain      = string
    timezone    = string
    environment = string
  })
}

variable "proxmox" {
  description = "Validated, non-secret Proxmox connection and placement settings."
  type = object({
    endpoint = string
    node     = string
    storage  = string
    token_id = string
    insecure = bool
  })

  validation {
    condition     = startswith(var.proxmox.endpoint, "https://")
    error_message = "The Proxmox endpoint must use HTTPS."
  }
}

variable "network" {
  description = "Validated management-network settings used by later resource modules."
  type = object({
    management_cidr = string
    gateway         = string
    dns_servers     = list(string)
    bridge          = string
    vlan_id         = optional(number)
  })
}

variable "cloudflare_domains" {
  description = "Validated public domains used by the later Cloudflare module."
  type        = list(string)
  default     = []
}

variable "proxmox_api_token" {
  description = "Runtime-only Proxmox API credential supplied through TF_VAR_proxmox_api_token."
  type        = string
  sensitive   = true
  nullable    = true
  default     = null
}
