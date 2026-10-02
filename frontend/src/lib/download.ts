import { getToken } from '@/api/client'

/** Authenticated file download (the API needs the bearer token, so a plain link will not do). */
export async function downloadFile(path: string, params: Record<string, string | undefined>, filename: string) {
  const url = new URL(`/api${path}`, window.location.origin)
  Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v))
  const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) {
    let msg = res.statusText
    try { msg = (await res.json()).detail ?? msg } catch { /* not json */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}
