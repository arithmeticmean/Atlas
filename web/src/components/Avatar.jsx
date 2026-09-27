// Initials avatar with a colour derived from the address.
//
// Deterministic, so the same person is the same colour on every screen and in
// every session -- that consistency is the only thing making an avatar useful
// for scanning a list. Tints are light enough to carry dark text at 4.5:1.
const TINTS = [
  '#a5b4fc', // indigo
  '#f0abfc', // fuchsia
  '#7dd3fc', // sky
  '#fcd34d', // amber
  '#6ee7b7', // emerald
  '#fda4af', // rose
]

function tintFor(seed) {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  return TINTS[hash % TINTS.length]
}

export function Avatar({ email, size = 30 }) {
  const seed = (email || '?').trim().toLowerCase()
  const initials = seed.slice(0, 2).toUpperCase()
  return (
    <span
      aria-hidden="true"
      className="shrink-0 rounded-full grid place-items-center font-bold text-bg"
      style={{
        width: size,
        height: size,
        background: tintFor(seed),
        fontSize: Math.round(size * 0.36),
      }}
    >
      {initials}
    </span>
  )
}
