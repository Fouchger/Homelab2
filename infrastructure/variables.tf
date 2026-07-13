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
  description = "Validated management-network settings inherited by managed guests."
  type = object({
    management_cidr = string
    gateway         = string
    dns_servers     = list(string)
    bridge          = string
    vlan_id         = optional(number)
  })
}

variable "automation" {
  description = "Public bootstrap material for managed guests."
  type = object({
    ssh_public_keys = list(string)
  })
}

variable "cloudflare_domains" {
  description = "Validated existing public zones in which records may be managed."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.cloudflare_domains) == length(distinct(var.cloudflare_domains))
    error_message = "Cloudflare domains must be unique."
  }
}

variable "proxmox_lxcs" {
  description = "OpenTofu-owned unprivileged Debian LXC guests."
  type = list(object({
    key              = string
    vm_id            = number
    hostname         = string
    template_file_id = string
    address          = string
    cores            = number
    memory_mb        = number
    swap_mb          = number
    disk_gb          = number
    started          = bool
    start_on_boot    = bool
    nesting          = bool
    protection       = bool
    tags             = list(string)
  }))
  default = []

  validation {
    condition     = length(var.proxmox_lxcs) == length(distinct([for guest in var.proxmox_lxcs : guest.key]))
    error_message = "Each Proxmox LXC key must be unique."
  }

  validation {
    condition     = length(var.proxmox_lxcs) == length(distinct([for guest in var.proxmox_lxcs : guest.vm_id]))
    error_message = "Each Proxmox LXC VM ID must be unique."
  }

  validation {
    condition     = length(var.proxmox_lxcs) == length(distinct([for guest in var.proxmox_lxcs : guest.hostname]))
    error_message = "Each Proxmox LXC hostname must be unique."
  }

  validation {
    condition     = length(var.proxmox_lxcs) == 0 || length(var.automation.ssh_public_keys) > 0
    error_message = "At least one automation SSH public key is required when Proxmox LXCs are configured."
  }
}

variable "cloudflare_records" {
  description = "OpenTofu-owned public A, AAAA, and CNAME records."
  type = list(object({
    zone    = string
    name    = string
    type    = string
    content = string
    ttl     = number
    proxied = bool
  }))
  default = []

  validation {
    condition = alltrue([
      for record in var.cloudflare_records :
      contains(var.cloudflare_domains, record.zone)
    ])
    error_message = "Every Cloudflare record zone must be present in cloudflare_domains."
  }

  validation {
    condition = alltrue([
      for record in var.cloudflare_records :
      contains(["A", "AAAA", "CNAME"], record.type)
    ])
    error_message = "Cloudflare records support only A, AAAA, and CNAME types."
  }

  validation {
    condition = alltrue([
      for record in var.cloudflare_records :
      record.ttl == 1 || (record.ttl >= 60 && record.ttl <= 86400)
    ])
    error_message = "Cloudflare record TTL must be 1 for automatic or between 60 and 86400 seconds."
  }

  validation {
    condition = length(var.cloudflare_records) == length(distinct([
      for record in var.cloudflare_records :
      "${record.zone}/${record.type}/${record.name}"
    ]))
    error_message = "Each Cloudflare zone, type, and name combination must be unique."
  }
}

variable "proxmox_api_token" {
  description = "Runtime-only Proxmox API credential supplied through TF_VAR_proxmox_api_token."
  type        = string
  sensitive   = true
  nullable    = true
  default     = null
}
