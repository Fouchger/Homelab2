locals {
  proxmox_lxc_by_key = {
    for guest in var.proxmox_lxcs : guest.key => guest
  }
}

resource "proxmox_virtual_environment_container" "managed" {
  for_each = local.proxmox_lxc_by_key

  description   = "Managed by Homelab Control Plane (${var.site.name})"
  node_name     = var.proxmox.node
  vm_id         = each.value.vm_id
  unprivileged  = true
  protection    = each.value.protection
  started       = each.value.started
  start_on_boot = each.value.start_on_boot
  tags = sort(distinct(concat(
    ["homelab", "managed-by-opentofu"],
    each.value.tags,
  )))

  features {
    nesting = each.value.nesting
  }

  cpu {
    cores = each.value.cores
  }

  memory {
    dedicated = each.value.memory_mb
    swap      = each.value.swap_mb
  }

  disk {
    datastore_id = var.proxmox.storage
    size         = each.value.disk_gb
  }

  initialization {
    hostname = each.value.hostname

    dns {
      domain  = var.site.domain
      servers = var.network.dns_servers
    }

    ip_config {
      ipv4 {
        address = each.value.address
        gateway = var.network.gateway
      }
    }

    user_account {
      keys = var.automation.ssh_public_keys
    }
  }

  network_interface {
    name     = "veth0"
    bridge   = var.network.bridge
    firewall = false
    vlan_id  = var.network.vlan_id
  }

  operating_system {
    template_file_id = each.value.template_file_id
    type             = "debian"
  }

  wait_for_ip {
    ipv4 = true
  }
}
