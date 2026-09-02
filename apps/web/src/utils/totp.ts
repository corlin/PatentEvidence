/**
 * Client-side TOTP calculation utility (RFC 6238) using Web Crypto API.
 * Helps development and manual testing when physical mobile devices have clock drift vs server.
 */

function base32Decode(base32: string): Uint8Array {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  const cleaned = base32.toUpperCase().replace(/=+$/, '')
  let bits = 0
  let value = 0
  const output: number[] = []
  for (let i = 0; i < cleaned.length; i++) {
    const val = alphabet.indexOf(cleaned[i])
    if (val === -1) continue
    value = (value << 5) | val
    bits += 5
    if (bits >= 8) {
      output.push((value >>> (bits - 8)) & 255)
      bits -= 8
    }
  }
  return new Uint8Array(output)
}

export async function generateTotpCode(secret: string, timestamp: number = Date.now()): Promise<string> {
  try {
    const counter = Math.floor(timestamp / 1000 / 30)
    const counterBytes = new Uint8Array(8)
    let tmp = counter
    for (let i = 7; i >= 0; i--) {
      counterBytes[i] = tmp & 0xff
      tmp = Math.floor(tmp / 256)
    }

    const keyBytes = base32Decode(secret)
    const key = await crypto.subtle.importKey(
      'raw',
      keyBytes as BufferSource,
      { name: 'HMAC', hash: 'SHA-1' },
      false,
      ['sign']
    )
    const signature = new Uint8Array(
      await crypto.subtle.sign('HMAC', key, counterBytes as BufferSource)
    )
    const offset = signature[signature.length - 1] & 0x0f
    const code = (
      ((signature[offset] & 0x7f) << 24) |
      ((signature[offset + 1] & 0xff) << 16) |
      ((signature[offset + 2] & 0xff) << 8) |
      (signature[offset + 3] & 0xff)
    ) % 1000000
    return code.toString().padStart(6, '0')
  } catch {
    return ''
  }
}
