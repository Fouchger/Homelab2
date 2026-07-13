provider "proxmox" {
  endpoint  = var.proxmox.endpoint
  api_token = var.proxmox_api_token
  insecure  = var.proxmox.insecure
}
