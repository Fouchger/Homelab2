locals {
  cloudflare_record_by_key = {
    for record in var.cloudflare_records :
    "${record.zone}/${record.type}/${record.name}" => record
  }
  cloudflare_record_zones = toset([
    for record in var.cloudflare_records : record.zone
  ])
}

data "cloudflare_zones" "managed" {
  for_each = local.cloudflare_record_zones

  name      = each.value
  status    = "active"
  match     = "all"
  max_items = 2
}

resource "cloudflare_dns_record" "managed" {
  for_each = local.cloudflare_record_by_key

  zone_id = (
    length(data.cloudflare_zones.managed[each.value.zone].result) == 1
    ? data.cloudflare_zones.managed[each.value.zone].result[0].id
    : "00000000000000000000000000000000"
  )
  name = (
    each.value.name == "@"
    ? each.value.zone
    : "${each.value.name}.${each.value.zone}"
  )
  type    = each.value.type
  content = each.value.content
  ttl     = each.value.ttl
  proxied = each.value.proxied
  comment = "Managed by Homelab Control Plane"

  lifecycle {
    precondition {
      condition     = length(data.cloudflare_zones.managed[each.value.zone].result) == 1
      error_message = "Cloudflare zone ${each.value.zone} must match exactly one active existing zone."
    }
  }
}
