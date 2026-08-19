export async function copyTextToClipboard(text: string): Promise<void> {
  const value = String(text || '').trim()
  if (!value || typeof document === 'undefined') throw new Error('Ссылка пока недоступна')

  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Telegram WebView can reject Clipboard API after an awaited request.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.inset = '-9999px auto auto -9999px'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('Не удалось скопировать ссылку')
}
