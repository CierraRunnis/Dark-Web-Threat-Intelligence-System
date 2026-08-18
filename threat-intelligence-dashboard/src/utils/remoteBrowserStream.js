function viewportPoint(event, image, viewport) {
  const width = Number(viewport?.width || 0)
  const height = Number(viewport?.height || 0)
  const bounds = image.getBoundingClientRect()
  if (!width || !height || !bounds.width || !bounds.height) return null

  const scale = Math.min(bounds.width / width, bounds.height / height)
  const renderedWidth = width * scale
  const renderedHeight = height * scale
  const left = bounds.left + (bounds.width - renderedWidth) / 2
  const top = bounds.top + (bounds.height - renderedHeight) / 2
  const x = (event.clientX - left) / scale
  const y = (event.clientY - top) / scale
  if (x < 0 || y < 0 || x > width || y > height) return null
  return { x: Math.round(x), y: Math.round(y) }
}

function mouseButton(button) {
  return ['left', 'middle', 'right'][Number(button)] || 'left'
}

export function createRemoteBrowserStream({ image, focusTarget, websocketUrl, onStatus, onError }) {
  let socket = null
  let viewport = null
  let moveFrame = 0
  let pendingMove = null

  const send = (payload) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload))
  }

  const sendMouse = (event, action) => {
    const point = viewportPoint(event, image, viewport)
    if (!point) return
    send({
      type: 'mouse',
      action,
      ...point,
      button: mouseButton(event.button),
      deltaX: Number(event.deltaX || 0),
      deltaY: Number(event.deltaY || 0),
    })
  }

  const onPointerMove = (event) => {
    pendingMove = event
    if (moveFrame) return
    moveFrame = window.requestAnimationFrame(() => {
      moveFrame = 0
      if (pendingMove) sendMouse(pendingMove, 'move')
      pendingMove = null
    })
  }
  const onPointerDown = (event) => {
    event.preventDefault()
    focusTarget.focus()
    sendMouse(event, 'down')
  }
  const onPointerUp = (event) => {
    event.preventDefault()
    sendMouse(event, 'up')
  }
  const onWheel = (event) => {
    event.preventDefault()
    sendMouse(event, 'wheel')
  }
  const onKeyDown = (event) => {
    event.preventDefault()
    const text = event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey ? event.key : ''
    send({ type: 'key', action: 'down', key: event.key, code: event.code, text })
  }
  const onKeyUp = (event) => {
    event.preventDefault()
    if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) return
    send({ type: 'key', action: 'up', key: event.key, code: event.code, text: '' })
  }
  const onContextMenu = (event) => event.preventDefault()

  image.addEventListener('pointermove', onPointerMove)
  image.addEventListener('pointerdown', onPointerDown)
  image.addEventListener('pointerup', onPointerUp)
  image.addEventListener('wheel', onWheel, { passive: false })
  image.addEventListener('contextmenu', onContextMenu)
  focusTarget.addEventListener('keydown', onKeyDown)
  focusTarget.addEventListener('keyup', onKeyUp)

  const connect = () => {
    onStatus?.('connecting')
    socket = new WebSocket(websocketUrl)
    socket.addEventListener('open', () => onStatus?.('connected'))
    socket.addEventListener('message', async (event) => {
      try {
        if (event.data instanceof Blob) {
          image.src = URL.createObjectURL(event.data)
          image.onload = () => URL.revokeObjectURL(image.src)
          image.hidden = false
          return
        }
        const message = JSON.parse(String(event.data || '{}'))
        if (message.width && message.height) viewport = { width: message.width, height: message.height }
        if (message.type === 'frame' && message.data) {
          image.src = `data:image/jpeg;base64,${message.data}`
          image.hidden = false
        } else if (message.type === 'error') {
          onError?.(message.message || '实时浏览器连接异常')
        }
      } catch (error) {
        onError?.(error.message || '实时浏览器画面解析失败')
      }
    })
    socket.addEventListener('error', () => onError?.('实时浏览器连接失败'))
    socket.addEventListener('close', () => onStatus?.('disconnected'))
  }

  const close = () => {
    if (moveFrame) window.cancelAnimationFrame(moveFrame)
    moveFrame = 0
    pendingMove = null
    image.removeEventListener('pointermove', onPointerMove)
    image.removeEventListener('pointerdown', onPointerDown)
    image.removeEventListener('pointerup', onPointerUp)
    image.removeEventListener('wheel', onWheel)
    image.removeEventListener('contextmenu', onContextMenu)
    focusTarget.removeEventListener('keydown', onKeyDown)
    focusTarget.removeEventListener('keyup', onKeyUp)
    socket?.close()
    socket = null
  }

  connect()
  return { close }
}
