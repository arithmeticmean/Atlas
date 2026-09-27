// How other devices reach this instance.
//
// Deliberately unrelated to invites. An invite token is a credential and is
// valid whatever address it is redeemed at, so it is never baked into a URL:
// locally the useful address is a LAN IP nobody wants to look up by hand, and
// in a deployment the address is already known. The server reports its own
// reachability (GET /network) because only it knows what interface it bound.

export function reachUrl(address, port) {
  return `http://${address}:${port}`
}
