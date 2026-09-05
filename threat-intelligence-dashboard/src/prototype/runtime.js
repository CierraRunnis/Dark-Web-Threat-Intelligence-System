import {
  AUTH_UNAUTHORIZED_EVENT,
  hasModuleAccess,
  isCurrentUserAdmin,
  logout,
} from '@/composables/useAuth'
import { MODULE_KEYS } from '@/config/permissions'
import { setupVersionStatus } from '@/prototype/versionStatus'


const ICONS = {
  overview: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 13h6V4H4v9Zm10 7h6V11h-6v9ZM4 20h6v-3H4v3Zm10-13h6V4h-6v3Z"/></svg>',
  intelligence: '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3m-3-7-2 2M7 17l-2 2"/></svg>',
  exposure: '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M6 12h3l2-4 3 8 2-4h2M9 21h6"/></svg>',
  collect: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 20V10m-4 10h8M8 8a5 5 0 0 1 8 0M5 5a9 9 0 0 1 14 0"/><circle cx="12" cy="7" r="2"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 6h7m4 0h5M4 12h3m4 0h9M4 18h9m4 0h3"/><circle cx="13" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="15" cy="18" r="2"/></svg>',
}


function currentUser() {
  try {
    return JSON.parse(localStorage.getItem('dwti-current-user') || 'null') || {}
  } catch {
    return {}
  }
}


function icon(name) {
  return `<span class="nav-icon" aria-hidden="true">${ICONS[name]}</span>`
}


function activeClass(path, currentPath) {
  if (path === '/' || path === '/settings') return currentPath === path ? ' active' : ''
  return currentPath === path || currentPath.startsWith(`${path}/`) ? ' active' : ''
}


function navLink(item, currentPath) {
  return `<a class="nav-link sub${activeClass(item.path, currentPath)}" href="${item.path}">${item.label}</a>`
}


function navGroup(name, iconName, items, currentPath) {
  if (!items.length) return ''
  return `
    <div class="nav-group">
      <div class="nav-group-title">${icon(iconName)}<span>${name}</span></div>
      <div class="nav-group-items">${items.map((item) => navLink(item, currentPath)).join('')}</div>
    </div>`
}


function renderSidebar(root) {
  const sidebar = root.querySelector('.app-sidebar')
  const nav = sidebar?.querySelector('.sidebar-nav')
  if (!sidebar || !nav) return
  const currentPath = window.location.pathname
  const threatItems = [
    hasModuleAccess(MODULE_KEYS.INTELLIGENCE_SEARCH) && { path: '/intelligence', label: '情报检索' },
    hasModuleAccess(MODULE_KEYS.AI_AGGREGATION) && { path: '/ai-aggregation', label: 'AI聚合' },
    hasModuleAccess(MODULE_KEYS.RANSOMWARE) && { path: '/ransomware', label: '勒索情报' },
    hasModuleAccess(MODULE_KEYS.DATA_LEAK) && { path: '/data-leak', label: '数据泄露情报' },
    hasModuleAccess(MODULE_KEYS.VULNERABILITY_ALERTS) && { path: '/vulnerability-alerts', label: '漏洞预警' },
  ].filter(Boolean)
  const exposureItems = hasModuleAccess(MODULE_KEYS.FILE_MONITORING)
    ? [
        { path: '/document-exposure/netdisk', label: '网盘监测' },
        { path: '/document-exposure/document-library', label: '文库监测' },
        { path: '/document-exposure/code-monitoring', label: '代码监测' },
      ]
    : []
  const collectorItems = hasModuleAccess(MODULE_KEYS.COLLECTOR_CONTROL)
    ? [{ path: '/collector-control', label: '采集控制' }]
    : []
  const systemItems = [
    hasModuleAccess(MODULE_KEYS.FILE_MONITORING) && { path: '/settings', label: '监测配置' },
    isCurrentUserAdmin() && { path: '/settings/data-migration', label: '数据迁移' },
    isCurrentUserAdmin() && { path: '/account-management', label: '账号管理' },
  ].filter(Boolean)

  const brand = sidebar.querySelector('.brand')
  if (brand) {
    brand.href = '/'
    brand.innerHTML = '<span class="brand-mark" aria-hidden="true"><img src="/assets/xuanjian-mark.svg?v=8" alt=""></span><span class="brand-copy"><strong>玄鉴</strong><span>XUANJIAN INTELLIGENCE</span></span>'
  }
  nav.innerHTML = [
    navGroup('威胁概况', 'overview', [{ path: '/', label: '总览' }], currentPath),
    navGroup('威胁情报', 'intelligence', threatItems, currentPath),
    navGroup('暴露监测', 'exposure', exposureItems, currentPath),
    navGroup('采集运营', 'collect', collectorItems, currentPath),
    navGroup('系统管理', 'settings', systemItems, currentPath),
  ].join('')
  const footer = sidebar.querySelector('.sidebar-footer')
  if (footer) footer.innerHTML = '<div class="sidebar-status"><i></i><span>监测服务运行中</span></div>'
}


function setupSidebar(root, signal) {
  const shell = root.querySelector('.app-shell')
  const sidebar = root.querySelector('.app-sidebar')
  if (!shell || !sidebar) return
  let pinnedExpanded = sessionStorage.getItem('dwti-prototype-sidebar-expanded') === '1'
  const mobile = window.matchMedia('(max-width: 900px)')

  const applyDesktopState = (hovered = false) => {
    if (mobile.matches) return
    shell.classList.toggle('sidebar-collapsed', !pinnedExpanded)
    shell.classList.toggle('sidebar-hover-expanded', !pinnedExpanded && hovered)
  }
  const closeMobile = () => shell.classList.remove('sidebar-open')

  applyDesktopState(false)
  sidebar.addEventListener('pointerenter', () => applyDesktopState(true), { signal })
  sidebar.addEventListener('pointerleave', () => applyDesktopState(false), { signal })
  sidebar.addEventListener('focusin', () => applyDesktopState(true), { signal })
  sidebar.addEventListener('focusout', (event) => {
    if (!sidebar.contains(event.relatedTarget)) applyDesktopState(false)
  }, { signal })

  root.querySelectorAll('[data-sidebar-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      if (mobile.matches) {
        shell.classList.toggle('sidebar-open')
        return
      }
      pinnedExpanded = !pinnedExpanded
      sessionStorage.setItem('dwti-prototype-sidebar-expanded', pinnedExpanded ? '1' : '0')
      applyDesktopState(false)
    }, { signal })
  })
  root.querySelector('.sidebar-backdrop')?.addEventListener('click', closeMobile, { signal })
  sidebar.querySelectorAll('a[href]').forEach((link) => {
    link.addEventListener('click', closeMobile, { signal })
  })
  mobile.addEventListener('change', () => {
    closeMobile()
    applyDesktopState(false)
  }, { signal })
}


function setupAccount(root, signal) {
  const user = currentUser()
  const avatar = root.querySelector('.app-header .avatar')
  if (!avatar) return
  avatar.textContent = String(user.display_name || user.username || '用户').slice(0, 4)
  avatar.setAttribute('role', 'button')
  avatar.setAttribute('tabindex', '0')
  avatar.setAttribute('aria-expanded', 'false')
  const menu = document.createElement('div')
  menu.className = 'account-dropdown prototype-account-dropdown'
  menu.hidden = true
  menu.innerHTML = `
    <strong>${user.display_name || user.username || '当前用户'}</strong>
    <small>${user.role === 'admin' || user.is_admin ? '管理员' : '分析员'}</small>
    <button type="button" data-prototype-logout>退出登录</button>`
  avatar.insertAdjacentElement('afterend', menu)
  const toggle = () => {
    menu.hidden = !menu.hidden
    avatar.setAttribute('aria-expanded', String(!menu.hidden))
  }
  avatar.addEventListener('click', toggle, { signal })
  avatar.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      toggle()
    }
  }, { signal })
  menu.querySelector('[data-prototype-logout]')?.addEventListener('click', async () => {
    await logout()
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT))
  }, { signal })
  document.addEventListener('click', (event) => {
    if (event.target === avatar || menu.contains(event.target)) return
    menu.hidden = true
    avatar.setAttribute('aria-expanded', 'false')
  }, { signal })
}


function controlState(root, tableId) {
  const table = root.querySelector(`#${CSS.escape(tableId)}`)
  const tabs = root.querySelector(`.tabs[data-target="${CSS.escape(tableId)}"]`)
  const search = root.querySelector(`[data-table-search="${CSS.escape(tableId)}"]`)
  const filters = [...root.querySelectorAll(`[data-filter-target="${CSS.escape(tableId)}"]`)]
  const dates = [...root.querySelectorAll(`[data-date-filter-target="${CSS.escape(tableId)}"]`)]
  return {
    page: Number(table?.dataset.serverPage || 1),
    pageSize: Number(table?.dataset.serverPageSize || 20),
    tab: tabs?.querySelector('.tab.active')?.dataset.tab || 'all',
    query: search?.value?.trim() || '',
    filters: Object.fromEntries(filters.map((control) => [control.dataset.filterKey || '', control.value])),
    days: Number(dates[0]?.value || 0) || null,
    sort: root.querySelector('[data-intel-sort]')?.value || 'latest',
  }
}


function dispatchQueryChange(root, tableId, resetPage = true) {
  const table = root.querySelector(`#${CSS.escape(tableId)}`)
  if (table && resetPage) table.dataset.serverPage = '1'
  root.dispatchEvent(new CustomEvent('prototype:query-change', {
    detail: { tableId, state: controlState(root, tableId) },
  }))
}


function setupServerControls(root, signal) {
  let searchTimer = null
  root.querySelectorAll('[data-table-search]').forEach((control) => {
    control.addEventListener('input', () => {
      window.clearTimeout(searchTimer)
      searchTimer = window.setTimeout(
        () => dispatchQueryChange(root, control.dataset.tableSearch),
        250,
      )
    }, { signal })
  })
  root.querySelectorAll('[data-filter-target], [data-date-filter-target]').forEach((control) => {
    control.addEventListener('change', () => {
      dispatchQueryChange(root, control.dataset.filterTarget || control.dataset.dateFilterTarget)
    }, { signal })
  })
  root.querySelector('[data-intel-sort]')?.addEventListener('change', () => {
    dispatchQueryChange(root, 'intel-results')
  }, { signal })
  root.querySelector('[data-intel-search-form]')?.addEventListener('submit', (event) => {
    event.preventDefault()
    dispatchQueryChange(root, 'intel-results')
  }, { signal })
  root.querySelectorAll('.tabs[data-target]').forEach((tabs) => {
    tabs.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        tabs.querySelectorAll('.tab').forEach((candidate) => {
          const active = candidate === tab
          candidate.classList.toggle('active', active)
          candidate.setAttribute('aria-selected', String(active))
        })
        dispatchQueryChange(root, tabs.dataset.target)
      }, { signal })
    })
  })
  signal.addEventListener('abort', () => window.clearTimeout(searchTimer), { once: true })
}


export function initializePrototype(root, { serverControls = true } = {}) {
  const controller = new AbortController()
  const { signal } = controller
  renderSidebar(root)
  setupSidebar(root, signal)
  setupAccount(root, signal)
  setupVersionStatus(root, signal)
  if (serverControls) setupServerControls(root, signal)
  return () => controller.abort()
}
