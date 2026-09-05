import { isCurrentUserAdmin } from '@/composables/useAuth'

const VERSION_CHECK_INTERVAL_MS = 5 * 60 * 1000

function currentVersionLabel(payload) {
  return payload?.current?.version || payload?.current?.short_commit || 'local'
}

function latestVersionLabel(payload) {
  return payload?.latest?.version || payload?.latest?.short_commit || '-'
}

export function setupVersionStatus(root, signal) {
  const badge = root.querySelector('.app-version')
  if (!badge) return
  if (!isCurrentUserAdmin()) {
    badge.remove()
    return
  }

  let button = badge
  if (badge.tagName !== 'BUTTON') {
    button = document.createElement('button')
    ;[...badge.attributes].forEach((attribute) => button.setAttribute(attribute.name, attribute.value))
    button.innerHTML = badge.innerHTML
    badge.replaceWith(button)
  }
  button.type = 'button'
  button.setAttribute('aria-label', '正式版本信息')
  button.setAttribute('aria-haspopup', 'dialog')
  button.setAttribute('aria-expanded', 'false')

  const wrapper = document.createElement('div')
  wrapper.className = 'version-menu'
  button.before(wrapper)
  wrapper.appendChild(button)

  const menu = document.createElement('section')
  menu.className = 'version-dropdown'
  menu.id = `version-dropdown-${Math.random().toString(36).slice(2)}`
  menu.setAttribute('role', 'dialog')
  menu.setAttribute('aria-label', '正式版本信息与检查')
  menu.hidden = true
  menu.innerHTML = `
    <div class="version-dropdown-head">
      <strong>正式版本</strong>
      <span class="version-state" data-version-state>检查中</span>
    </div>
    <strong class="version-title" data-version-title>检查中</strong>
    <p class="version-description" data-version-description>正在检查 GitHub 正式版本</p>
    <a class="version-compare-link" data-version-link target="_blank" rel="noreferrer" hidden>查看正式版本</a>
    <button type="button" class="btn btn-secondary version-check-action" data-version-refresh>立即检查</button>`
  wrapper.appendChild(menu)
  button.setAttribute('aria-controls', menu.id)

  const badgeVersion = button.querySelector('strong')
  const stateNode = menu.querySelector('[data-version-state]')
  const titleNode = menu.querySelector('[data-version-title]')
  const descriptionNode = menu.querySelector('[data-version-description]')
  const linkNode = menu.querySelector('[data-version-link]')
  const refreshButton = menu.querySelector('[data-version-refresh]')
  let payload = null
  let loading = false

  const render = (error = '') => {
    const updateAvailable = Boolean(payload?.update_available)
    const current = currentVersionLabel(payload)
    const latest = latestVersionLabel(payload)
    const branch = payload?.branch || payload?.latest?.branch || '正式发布分支'
    if (badgeVersion) badgeVersion.textContent = current
    button.classList.toggle('has-update', updateAvailable)
    button.classList.toggle('is-busy', loading)
    menu.dataset.state = error ? 'error' : loading ? 'loading' : updateAvailable ? 'available' : 'current'
    stateNode.textContent = error ? '异常' : loading ? '检查中' : updateAvailable ? '有更新' : '已同步'
    titleNode.textContent = error ? '检查失败' : updateAvailable ? `发现 ${latest}` : `当前 ${current}`
    descriptionNode.textContent = error
      || (updateAvailable
        ? `当前 ${current}，${branch} 已发布 ${latest}`
        : `${branch} · ${latest}`)
    const targetUrl = payload?.compare_url || payload?.latest?.html_url || ''
    linkNode.hidden = !targetUrl
    if (targetUrl) linkNode.href = targetUrl
    linkNode.textContent = updateAvailable ? '查看版本差异' : '查看正式版本'
    refreshButton.disabled = loading
    refreshButton.textContent = loading ? '正在检查…' : '立即检查'
  }

  const load = async (force = false) => {
    if (loading) return
    loading = true
    render()
    try {
      const suffix = force ? '?force=true' : ''
      const response = await fetch(`/api/system/version${suffix}`, { cache: 'no-store', signal })
      if (!response.ok) throw new Error(`版本检查失败：${response.status}`)
      payload = await response.json()
      if (payload.status === 'error') {
        throw new Error(payload.error || payload.message || '无法检查 GitHub 正式版本')
      }
      loading = false
      render()
    } catch (error) {
      if (error.name === 'AbortError') return
      loading = false
      render(error.message || '无法检查 GitHub 正式版本')
    }
  }

  const close = () => {
    menu.hidden = true
    button.setAttribute('aria-expanded', 'false')
  }
  button.addEventListener('click', (event) => {
    event.stopPropagation()
    const willOpen = menu.hidden
    root.querySelectorAll('.version-dropdown').forEach((item) => { item.hidden = true })
    menu.hidden = !willOpen
    button.setAttribute('aria-expanded', String(willOpen))
    if (willOpen) load()
  }, { signal })
  refreshButton.addEventListener('click', () => load(true), { signal })
  document.addEventListener('click', (event) => {
    if (!wrapper.contains(event.target)) close()
  }, { signal })
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close()
  }, { signal })

  load()
  const interval = window.setInterval(load, VERSION_CHECK_INTERVAL_MS)
  signal.addEventListener('abort', () => window.clearInterval(interval), { once: true })
}
