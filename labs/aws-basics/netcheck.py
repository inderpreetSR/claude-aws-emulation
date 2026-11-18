"""Explain whether a packet would be allowed, using the rules stored in the emulator.

The emulator stores security groups and network ACLs exactly as AWS does, but it does not
move packets. This module applies AWS's documented evaluation rules to those stored rules,
so you can see *why* traffic is allowed or blocked:

  * Security groups are STATEFUL: only the direction that starts the connection is
    checked; the reply is allowed automatically. They only contain allow rules.
  * Network ACLs are STATELESS: the request and the reply are each checked, in their own
    direction. Rules run in rule-number order, the first match wins, and they can deny.
"""
from __future__ import annotations

import ipaddress

PROTOCOL_NUMBERS = {"tcp": "6", "udp": "17", "icmp": "1", "all": "-1"}


def _ip_in(ip: str, cidr: str) -> bool:
    return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)


def nacl_decision(acl: dict, egress: bool, protocol: str, port: int, peer_ip: str):
    """First matching entry in rule-number order. Returns (allowed, rule number)."""
    proto = PROTOCOL_NUMBERS[protocol]
    for e in sorted((e for e in acl["Entries"] if e["Egress"] == egress), key=lambda e: e["RuleNumber"]):
        if e["Protocol"] not in ("-1", proto):
            continue
        rng = e.get("PortRange")
        if rng and not rng["From"] <= port <= rng["To"]:
            continue
        if not _ip_in(peer_ip, e.get("CidrBlock", "0.0.0.0/0")):
            continue
        return e["RuleAction"] == "allow", e["RuleNumber"]
    return False, "*"


def sg_allows(group: dict, egress: bool, protocol: str, port: int, peer_ip: str, peer_groups=()):
    """Any matching allow rule. Returns (allowed, the rule that matched or None)."""
    for p in group["IpPermissionsEgress" if egress else "IpPermissions"]:
        if p["IpProtocol"] not in ("-1", protocol):
            continue
        if p["IpProtocol"] != "-1" and "FromPort" in p and not p["FromPort"] <= port <= p["ToPort"]:
            continue
        for r in p.get("IpRanges", []):
            if _ip_in(peer_ip, r["CidrIp"]):
                return True, f'{p["IpProtocol"]} {p.get("FromPort", "all")} from {r["CidrIp"]}'
        for pair in p.get("UserIdGroupPairs", []):
            if pair["GroupId"] in peer_groups:
                return True, f'{p["IpProtocol"]} {p.get("FromPort", "all")} from {pair["GroupId"]}'
    return False, None


def check_inbound(name, *, src_ip, src_port, dst_port, protocol, target_sg, target_acl, src_groups=()):
    """Traffic arriving at an instance from src_ip. Returns one row of explanation."""
    acl_in, acl_in_rule = nacl_decision(target_acl, False, protocol, dst_port, src_ip)
    sg_in, sg_rule = sg_allows(target_sg, False, protocol, dst_port, src_ip, src_groups)
    # The reply leaves the subnet towards the client's ephemeral port: the NACL checks it again.
    acl_out, acl_out_rule = nacl_decision(target_acl, True, protocol, src_port, src_ip)
    if not acl_in:
        verdict = f"Blocked by NACL inbound rule {acl_in_rule}"
    elif not sg_in:
        verdict = "Blocked: no security group rule allows it"
    elif not acl_out:
        verdict = f"Request arrives, reply blocked by NACL outbound rule {acl_out_rule}"
    else:
        verdict = "Allowed"
    return {
        "scenario": name,
        "NACL inbound": f'{"allow" if acl_in else "deny"} (rule {acl_in_rule})',
        "security group": f"allow ({sg_rule})" if sg_in else "no matching rule",
        "NACL outbound (reply)": f'{"allow" if acl_out else "deny"} (rule {acl_out_rule})',
        "result": verdict,
    }
