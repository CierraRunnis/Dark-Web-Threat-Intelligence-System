export const LOOPBACK_ONLY_AI_PATH = '/api/ai/intelligence'

function requestPathname(rawUrl) {
  try {
    return decodeURIComponent(new URL(String(rawUrl || ''), 'http://127.0.0.1').pathname)
  } catch {
    return ''
  }
}


export function createLoopbackOnlyApiProxyBlocker() {
  return (request, response, next) => {
    const pathname = requestPathname(request.url)
    if (![LOOPBACK_ONLY_AI_PATH, `${LOOPBACK_ONLY_AI_PATH}/`].includes(pathname)) {
      return next()
    }

    response.statusCode = 403
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader(
      'Content-Type',
      'application/json; charset=utf-8',
    )
    response.end(
      JSON.stringify({
        detail: '该接口仅允许直接通过 127.0.0.1:8000 本地访问',
      }),
    )
  }
}
