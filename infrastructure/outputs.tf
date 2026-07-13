output "foundation" {
  description = "Non-secret validated values available to later infrastructure modules."
  value = {
    site_name          = var.site.name
    environment        = var.site.environment
    proxmox_node       = var.proxmox.node
    proxmox_storage    = var.proxmox.storage
    management_bridge  = var.network.bridge
    cloudflare_domains = var.cloudflare_domains
    proxmox_lxc_count  = length(var.proxmox_lxcs)
    dns_record_count   = length(var.cloudflare_records)
  }
}

output "proxmox_lxcs" {
  description = "Structured guest identity and initial SSH targets for later Ansible inventory."
  value = {
    for key, guest in proxmox_virtual_environment_container.managed :
    key => {
      vm_id              = guest.vm_id
      hostname           = local.proxmox_lxc_by_key[key].hostname
      node               = guest.node_name
      management_address = split("/", local.proxmox_lxc_by_key[key].address)[0]
      ssh_target         = "root@${split("/", local.proxmox_lxc_by_key[key].address)[0]}"
    }
  }
}

output "cloudflare_dns_records" {
  description = "Non-secret identity of public DNS records owned by OpenTofu."
  value = {
    for key, record in cloudflare_dns_record.managed :
    key => {
      id      = record.id
      zone    = local.cloudflare_record_by_key[key].zone
      name    = record.name
      type    = record.type
      proxied = record.proxied
    }
  }
}
