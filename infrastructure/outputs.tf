output "foundation" {
  description = "Non-secret validated values available to later infrastructure modules."
  value = {
    site_name          = var.site.name
    environment        = var.site.environment
    proxmox_node       = var.proxmox.node
    proxmox_storage    = var.proxmox.storage
    management_bridge  = var.network.bridge
    cloudflare_domains = var.cloudflare_domains
  }
}
